# SQLCoach API

SQLCoach is primarily a CLI tool, but its analysis pipeline can be used as a
library. Every public module, class, and function carries a docstring
describing its parameters, return value, and behavior — those docstrings are
the authoritative API reference; this page is an orientation to the entry
points.

## Application services

The highest-level entry points mirror the CLI commands. They return plain data
models (no printing), so you can consume the results programmatically.

```python
from pathlib import Path
from sqlcoach.reports.services import analyze_service

result = analyze_service(Path("queries.sql"))          # static analysis
for rec in result.recommendations:
    print(rec.problem, "->", rec.recommended_solution)
```

- `sqlcoach.reports.services.analyze_service(source, *, db_url=None,
  confirm_mutations=False, settings=None) -> AnalyzeResult`
- `sqlcoach.reports.comparison.compare_service(before, after, *, db_url=None,
  ...) -> ComparisonResult`
- `sqlcoach.reports.audit_service.audit_service(db_url, *, ...) -> AuditResult`

## Core building blocks

If you want finer control than the services, the pipeline is composable:

- **Parsing** — `sqlcoach.parser.sql_file_parser.SqlFileParser`,
  `sqlcoach.parser.log_parser.LogParser`,
  `sqlcoach.parser.plan_json_parser.parse_explain_json`.
- **Database** — `sqlcoach.database.connection.DatabaseConnection`,
  `sqlcoach.database.explain_runner.ExplainRunner`,
  `sqlcoach.database.pg_stat_statements`, `sqlcoach.database.index_catalog`.
- **Analysis** — `sqlcoach.analyzer.plan_analyzer.PlanAnalyzer`,
  `sqlcoach.advisor.index_advisor.IndexAdvisor`,
  `sqlcoach.advisor.anti_patterns.analyzer.AntiPatternAnalyzer`.
- **Unification** — `sqlcoach.advisor.recommendation_engine.RecommendationEngine`.

## Domain models

All models are frozen Pydantic models (`sqlcoach.models` and the finding types):
`Query`, `ExecutionPlan` / `PlanNode`, `Recommendation` / `ConfidenceLevel`,
`IndexRecommendation`, `Report`, and the finding types (`Finding`,
`AntiPatternFinding`, `IndexHygieneFinding`). Being frozen, they're safe to pass
around and compare.

## Configuration

`sqlcoach.config.load_settings()` returns a validated, immutable `Settings`
instance following the defaults < file < environment precedence. Pass it into
the services to control thresholds.

## Errors

Everything SQLCoach raises is a subclass of
`sqlcoach.exceptions.SQLCoachError` (`ConfigError`, `ValidationError`,
`ParsingError`, `DatabaseConnectionError`, `MutatingStatementError`). Raw
`psycopg` and `sqlglot` exceptions are wrapped before they reach you.