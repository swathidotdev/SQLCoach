# SQLCoach User Guide

SQLCoach reads your SQL (from a file or a live database) and produces a ranked
list of performance recommendations, each explaining the problem, the cause,
the fix, and the expected impact. This guide walks through the common workflows.

For exact flags and exit codes, see the [CLI reference](cli.md).

## Installation

```bash
pip install -e .
```

## Workflow 1: analyze a SQL file (no database)

The fastest way to get value — point SQLCoach at a `.sql` file. It runs the
static anti-pattern checks with no database required:

```bash
sqlcoach analyze queries.sql
```

You'll get recommendations for issues it can find from the SQL alone:
`SELECT *`, leading-wildcard `LIKE`, `ORDER BY RANDOM()`, and N+1 patterns
(many near-identical queries that suggest one-query-per-row application loops).
Each recommendation is printed with its problem, root cause, why it happens,
the fix, expected impact, and a confidence rating — highest impact first.

## Workflow 2: analyze against a live database

Add `--db-url` and SQLCoach also runs `EXPLAIN ANALYZE` on each query, inspects
the execution plans, and recommends indexes:

```bash
sqlcoach analyze queries.sql --db-url postgres://localhost/mydb
```

Now you additionally get plan-level findings (sequential scans, nested-loop
joins at scale, disk-spilling sorts, cardinality misestimation) and ready-to-run
`CREATE INDEX` statements, with quantified impact estimates where the plan data
supports them (for example, "currently examines ~500,000 rows").

SQLCoach never runs statements that modify data. If a query in your file is an
`INSERT`/`UPDATE`/`DELETE` (or takes locks), it's skipped unless you explicitly
pass `--confirm-mutations`.

## Workflow 3: confirm an optimization helped

After you rewrite a query or add an index, compare the before and after:

```bash
sqlcoach compare before.sql after.sql
```

SQLCoach reports which issues your change **resolved**, which it **introduced**,
and which **remain**, then gives a verdict (Improvement / Regression / Mixed /
No change). With `--db-url`, it also shows the plan-shape change
(`Seq Scan -> Index Scan`), the estimated-cost delta, and the observed
execution-time delta.

## Workflow 4: audit a whole database

To health-check an entire database in one read-only pass:

```bash
sqlcoach audit --db-url postgres://localhost/mydb
```

The audit covers the busiest queries (from `pg_stat_statements`), duplicate
indexes, and unused indexes, unified into one ranked report. Each section
degrades gracefully — if, say, `pg_stat_statements` isn't enabled, that section
is skipped with a note and the rest still runs. Index-hygiene findings come with
a generated `DROP INDEX` and a reminder to verify before dropping; SQLCoach never
drops anything itself, and never touches `UNIQUE`/`PRIMARY KEY` indexes.

## Interpreting a recommendation

Every recommendation has two independent ratings:

- **Impact** (its ranking) — how much the issue costs if it's real.
- **Confidence** — how sure SQLCoach is that it's real.

These are separate on purpose. A `SELECT *` is *high confidence* (it's plainly
there) but *low impact*, so it ranks below a costly sequential scan even if the
scan's estimate is less certain. Impact estimates are always labeled as
estimates — verify a suggested index by creating it and re-running the analysis.

## Configuration

SQLCoach reads settings from `./sqlcoach.toml` if present, then environment
variables (which win). Every setting has a `SQLCOACH_`-prefixed variable, e.g.:

```toml
# sqlcoach.toml
seq_scan_row_threshold = 10000
covering_index_max_included_columns = 3
n_plus_one_min_occurrences = 5
```

```bash
# equivalently, per-run:
SQLCOACH_SEQ_SCAN_ROW_THRESHOLD=50000 sqlcoach analyze queries.sql
```

## Where to go next

- [CLI reference](cli.md) — every command, flag, and exit code.
- [Architecture](architecture.md) — how SQLCoach is put together.
- [Contributing](contributing.md) — including how to add your own detector.