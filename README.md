# SQLCoach

**A PostgreSQL-first SQL performance analyzer and index advisor.**

SQLCoach reads your SQL — from a file, a query log, or a live database — and
produces a ranked list of performance recommendations, each explaining *what's
wrong, why, how to fix it, and the expected impact*. It's a performance coach
for your database: workload-level analysis and prioritized, explainable advice,
not just an EXPLAIN visualizer.

## Quickstart

```bash
pip install -e .

# Analyze a SQL file — no database needed:
sqlcoach analyze queries.sql
```

That alone flags `SELECT *`, leading-wildcard `LIKE`, `ORDER BY RANDOM()`, and
N+1 patterns, ranked by impact and fully explained.

Point it at a live database for the full picture — execution-plan analysis and
ready-to-run index recommendations:

```bash
sqlcoach analyze queries.sql --db-url postgres://localhost/mydb
```

## What it does

- **Analyze** SQL files, query logs, or live workloads into ranked, explained
  recommendations.
- **Detect anti-patterns** statically (no database required).
- **Recommend indexes** — single-column, composite, and covering — with
  ready-to-run `CREATE INDEX` SQL.
- **Compare** before/after versions of a query to confirm an optimization
  helped.
- **Audit** a whole database read-only: duplicate/unused indexes, slow queries,
  and anti-patterns in one pass.
- **Estimate impact** honestly — order-of-magnitude, always labeled as an
  estimate to verify.

Every recommendation includes Problem, Root Cause, Technical Explanation,
Recommended Solution, SQL Example, Expected Impact, Confidence, and Risks.

## Commands

| Command | What it does |
|---|---|
| `sqlcoach analyze <file> [--db-url ...]` | Analyze a workload |
| `sqlcoach compare <before> <after>` | Diff two versions of a query |
| `sqlcoach audit --db-url ...` | Full read-only database health check |
| `sqlcoach report <output>` | (Planned) generate a report file |

See the [CLI reference](docs/cli.md) for full details.

## Safety

SQLCoach is read-first: it never runs data-modifying statements (they're
skipped unless you pass `--confirm-mutations`), and it only ever *generates*
`CREATE INDEX` / `DROP INDEX` SQL for you to run — it never executes them.

## Documentation

- [User Guide](docs/user_guide.md) — common workflows, start here.
- [CLI Reference](docs/cli.md) — every command, flag, and exit code.
- [Architecture](docs/architecture.md) — how it's built.
- [API](docs/api.md) — using SQLCoach as a library.
- [Contributing](docs/contributing.md) — setup, standards, adding a detector.

## Development

```bash
pip install -e ".[dev]"
pytest -q                     # fast unit suite (no database)
```

Integration and performance tests are opt-in — see
[Contributing](docs/contributing.md).

## Technology

Python 3.12+ · PostgreSQL · psycopg3 · Typer · Pydantic · sqlglot · pytest.

## Status

Phases 1–6 complete (foundation through documentation). Release engineering
(packaging, Docker, CI/CD) is the final phase.