# SQLCoach CLI Reference

`sqlcoach` analyzes SQL workloads, detects anti-patterns, recommends indexes
and query rewrites, compares before/after versions, and audits live databases —
turning raw SQL and execution plans into ranked, explained recommendations.

Every example in this document is exercised by the test suite
(`tests/test_doc_examples.py`), so the database-free examples here are
guaranteed to run.

## Installation

```bash
pip install -e .
```

## Global options

These apply to every command and must appear **before** the command name:

- `--config PATH` — path to a `sqlcoach.toml` configuration file. Defaults to
  `./sqlcoach.toml` if present; otherwise built-in defaults are used.
- `--json-logs` — emit structured single-line JSON logs instead of
  human-readable text (useful in CI).

```bash
sqlcoach --help
```

Configuration precedence is: built-in defaults < `sqlcoach.toml` < environment
variables (each setting also has a `SQLCOACH_`-prefixed environment variable).

## `analyze` — analyze a SQL workload

Parses a `.sql` file into queries and always runs the static anti-pattern
checks (SELECT *, leading-wildcard LIKE, ORDER BY RANDOM(), N+1). When a
database URL is given, it additionally runs `EXPLAIN (ANALYZE, BUFFERS, FORMAT
JSON)` on each query, analyzes the execution plans, and recommends indexes.
All findings are unified into one ranked, fully-explained recommendation list.

**Argument:** `SOURCE` — path to a `.sql` file.

**Options:**
- `--db-url TEXT` — PostgreSQL connection string. Without it, only static
  analysis runs (no execution plans, no index recommendations).
- `--confirm-mutations` — allow `EXPLAIN ANALYZE` to run statements that modify
  data or take locks. Off by default; such statements are skipped otherwise.

Static analysis, no database required:

```bash
sqlcoach analyze queries.sql
```

Full analysis against a live database:

```bash
sqlcoach analyze queries.sql --db-url postgres://user:pass@localhost/mydb
```

Each recommendation is printed with its problem, root cause, technical
explanation, recommended fix, ready-to-run SQL (when applicable), expected
impact, and confidence — highest impact first.

## `compare` — diff two versions of a query

Runs the analyze pipeline on a "before" and an "after" file and reports what
changed: which anti-patterns and plan issues were resolved, introduced, or
remain, and (with `--db-url`) the plan-shape, estimated-cost, and execution-time
deltas. Structural diffs and estimated cost are deterministic; execution time
is shown but labeled as an observed measurement.

**Arguments:** `BEFORE` and `AFTER` — the two `.sql` files to compare.

**Options:** `--db-url TEXT`, `--confirm-mutations` (as for `analyze`).

```bash
sqlcoach compare before.sql after.sql
```

The output ends with a verdict: Improvement, Regression, Mixed, or No change.

## `audit` — full database health check

Inspects a live database in one read-only pass: the top workload queries (via
`pg_stat_statements`), duplicate indexes, and unused indexes, unified into a
ranked report. Each section degrades gracefully — a missing prerequisite (for
example `pg_stat_statements` not enabled) skips that section with a note rather
than failing the whole audit. `DROP INDEX` statements are generated but never
executed.

**Options:** `--db-url TEXT` (required), `--confirm-mutations`.

```bash
sqlcoach audit --db-url postgres://user:pass@localhost/mydb
```

## `report` — generate a report (planned)

Not yet implemented. Human-readable HTML/visual reporting is planned future
work; today, `analyze`, `compare`, and `audit` print their reports directly to
the terminal.

```bash
sqlcoach report output.json
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Configuration error |
| 2 | Usage error (bad or missing arguments; from the CLI framework) |
| 3 | Validation error (e.g. a required input was not provided) |
| 4 | Parsing error |
| 5 | Database connection error |
| 6 | Refused to run a mutating statement without `--confirm-mutations` |