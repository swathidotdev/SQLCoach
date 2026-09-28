# SQLCoach Architecture

SQLCoach turns SQL workloads and PostgreSQL execution plans into ranked, fully-explained optimization recommendations. It follows Clean Architecture:

* dependencies point inward toward the domain models,
* business logic never lives in the CLI, and
* no raw third-party exception ever crosses a layer boundary.

## Layers and Dependency Direction

Outer layers depend on inner ones; never the reverse.

```text
CLI (cli/main.py)
  |
  | parses args, invokes a service, renders output; owns exit codes
  v
Application services (reports/services.py, reports/comparison.py,
reports/audit_service.py)
  |
  | orchestrate parse -> analyze -> advise -> unify
  v
Domain logic (parser/, analyzer/, advisor/)
  |
  | pure logic over data models; no CLI, no formatting
  v
Domain models (models/) <-- everything depends inward on these
```

The database layer (`database/`) and cross-cutting concerns (`config.py`, `logging_config.py`, `redaction.py`, `exceptions.py`) sit beside these; domain logic depends on the *models* the database layer produces, not on the database layer itself.

## Data Flow

```text
SQL file / log                     live database (--db-url)
       |                                   |
       v                                   v
  parser/                              database/
       |                                   |
  SqlFileParser                    DatabaseConnection
  LogParser                        ExplainRunner (EXPLAIN ANALYZE)
       |                            pg_stat_statements
       |                            index_catalog
       v                                   v
  Query objects                 ExecutionPlan / IndexInfo / IndexUsage
       |                                   |
       +-------------------+---------------+
                           v
              Four independent finding sources
              +----------------+----------------+
              |                |                |
              v                v                v
        anti-patterns     plan analysis    index advisor
        (static, AST)     (PlanAnalyzer)   (IndexAdvisor)
              |                |                |
              +----------------+----------------+
                               |
                               v
                     index hygiene
                  (dup/unused idx)
                               |
                               v
                    RecommendationEngine
                    (merge overlaps, dedup,
                     rank by impact -> occurrences
                     -> confidence)
                               |
                               v
                   ranked Recommendation list
                               |
                               v
                         CLI renders it
```

## The Four Finding Sources

The recommendation engine unifies four independent producers. Keeping them separate (each a cohesive module) is what let them be built and tested in isolation across sprints:

1. **Anti-patterns** (`advisor/anti_patterns/`) — static AST checks (`SELECT *`, leading-wildcard `LIKE`, `ORDER BY RANDOM()`, N+1). No database needed.

2. **Plan analysis** (`analyzer/`) — inspects an `ExecutionPlan` for sequential scans, nested-loop joins at scale, disk-spilling sorts, and cardinality misestimation. Needs a live database (`EXPLAIN ANALYZE`).

3. **Index advisor** (`advisor/index_advisor.py`) — finding-driven: recommends single-column, composite, and covering indexes for tables flagged with a large sequential scan.

4. **Index hygiene** (`advisor/duplicate_index_detector.py`, `advisor/unused_index_detector.py`) — reads the catalog to flag redundant and unused indexes for dropping. Needs a live database.

## Key Design Invariants

* **Severity vs confidence are separate axes.** Severity is "how bad if real" (drives ranking); confidence is "how sure are we it's real" (`advisor/confidence.py`). A `SELECT *` is high confidence but low impact, so it ranks below a costly-but-estimated issue.

* **The engine folds overlaps, never double-reports.** An index recommendation *is* the fix for a sequential-scan finding on the same table, so the engine emits the index recommendation and folds the scan finding into it.

* **Deterministic output.** Diffs and rankings use stable keys and sorted set-differences, so identical inputs always produce identical output.

* **Generated SQL is never executed.** `CREATE INDEX` and `DROP INDEX` are produced as text for the user to run; SQLCoach only ever reads.

* **Errors are wrapped at the boundary.** Every `psycopg` / `sqlglot` error is translated into the `SQLCoachError` hierarchy before it can reach the CLI.

## Extensibility

Both detector families use the same pluggable-registry pattern: a `Protocol` defines the detector interface, a `default_detectors()` function is the single registration point, and an orchestrator runs every registered detector.

Adding a detector is one new module plus one line in the registry — no existing code changes (Open/Closed Principle). See `docs/contributing.md` for a worked example.

## Module Map

| Package                                                           | Responsibility                                                         |
| ----------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `cli/`                                                            | Argument parsing, output rendering, exit-code mapping                  |
| `reports/`                                                        | Application services: analyze / compare / audit orchestration          |
| `parser/`                                                         | SQL and log parsing, EXPLAIN-JSON parsing, shared AST helpers          |
| `analyzer/`                                                       | Execution-plan detectors and the `PlanAnalyzer`                        |
| `advisor/`                                                        | Index advice, anti-patterns, confidence, impact, recommendation engine |
| `database/`                                                       | psycopg3 connection, EXPLAIN runner, pg_stat_statements, index catalog |
| `models/`                                                         | Frozen Pydantic domain models (the inward dependency for everything)   |
| `config.py`, `logging_config.py`, `redaction.py`, `exceptions.py` | Cross-cutting concerns                                                 |
