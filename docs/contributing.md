# Contributing to SQLCoach

## Local setup

Requires Python 3.12+.

```bash
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -e ".[dev]"
```

## Running the tests

The default run is fast and needs no database or Docker:

```bash
pytest -q
```

Integration tests (real PostgreSQL) and performance tests are opt-in via
environment variables, so they skip cleanly by default:

```bash
# Integration tests against a disposable dockerized Postgres:
docker compose -f docker-compose.test.yml up -d
docker compose -f docker-compose.test.yml exec postgres \
  psql -U sqlcoach -d sqlcoach_test -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;"
# Windows PowerShell:
$env:SQLCOACH_TEST_DB_URL = "postgresql://sqlcoach:sqlcoach@localhost:5433/sqlcoach_test"
pytest -m integration -v

# Performance test (10,000-query workload):
$env:SQLCOACH_RUN_PERF = "1"
pytest -m performance -v
```

## Coding standards

- Target Python 3.12+; type hints and docstrings on all public code.
- Domain models are frozen Pydantic models with `extra="forbid"`.
- Business logic never lives in a CLI command function.
- Never let a raw `psycopg` or `sqlglot` exception escape a layer — wrap it in
  the `SQLCoachError` hierarchy.
- Prefer the standard library; new dependencies need justification.

## Walkthrough: adding a new anti-pattern detector

Anti-pattern detection uses a pluggable registry, so adding a detector requires
**one new module and one line** — no changes to existing detectors or the
analyzer. Here's a complete, working example: flagging a `LIMIT` without an
`ORDER BY` (which returns an arbitrary, non-deterministic subset of rows).

### 1. Write the detector

Create `src/sqlcoach/advisor/anti_patterns/unordered_limit.py`:

```python
"""Unordered-LIMIT detector: LIMIT without ORDER BY."""

from __future__ import annotations

from typing import Sequence

from sqlcoach.advisor.anti_patterns.base import AntiPatternFinding, ParsedQuery
from sqlcoach.analyzer.base import Severity

_CODE = "UNORDERED_LIMIT"


class UnorderedLimitDetector:
    name = "unordered_limit"

    def detect(
        self, parsed_queries: Sequence[ParsedQuery]
    ) -> list[AntiPatternFinding]:
        findings: list[AntiPatternFinding] = []
        for parsed in parsed_queries:
            statement = parsed.statement
            if statement is None:
                continue
            has_limit = statement.args.get("limit") is not None
            has_order = statement.args.get("order") is not None
            if has_limit and not has_order:
                findings.append(
                    AntiPatternFinding(
                        code=_CODE,
                        detector=self.name,
                        severity=Severity.LOW,
                        summary=(
                            "LIMIT without ORDER BY returns an arbitrary, "
                            "non-deterministic subset of rows; add an ORDER BY."
                        ),
                        source_location=parsed.query.source_location,
                    )
                )
        return findings
```

A detector is any object with a `name` attribute and a conforming `detect`
method — no base class to inherit. It receives the whole workload of
`ParsedQuery` objects (each a `Query` plus its parsed AST, already parsed once
for you) and returns findings. A query that couldn't be parsed has
`statement is None`; skip it.

### 2. Register it

Add one line to `default_detectors()` in
`src/sqlcoach/advisor/anti_patterns/analyzer.py`:

```python
from sqlcoach.advisor.anti_patterns.unordered_limit import UnorderedLimitDetector

def default_detectors(n_plus_one_min_occurrences=DEFAULT_MIN_OCCURRENCES):
    return (
        SelectStarDetector(),
        LeadingWildcardLikeDetector(),
        OrderByRandomDetector(),
        NPlusOneDetector(min_occurrences=n_plus_one_min_occurrences),
        UnorderedLimitDetector(),   # <-- the only change
    )
```

### 3. Give it a recommendation template

So the recommendation engine can explain it, add an entry to
`_ANTI_PATTERN_TEMPLATES` in `src/sqlcoach/advisor/recommendation_builders.py`
keyed by your code (`"UNORDERED_LIMIT"`), and a confidence in
`_ANTI_PATTERN_CONFIDENCE` in `src/sqlcoach/advisor/confidence.py`. A test
guarantees every detector code has a template, so you'll be reminded if you
forget.

### 4. Test it

Create `tests/test_detector_unordered_limit.py`:

```python
from sqlcoach.advisor.anti_patterns.unordered_limit import UnorderedLimitDetector
from sqlcoach.advisor.anti_patterns.analyzer import AntiPatternAnalyzer
from sqlcoach.models.query import Query, QuerySource


def _q(text):
    return Query(text=text, source=QuerySource.SQL_FILE, source_location="q:1")


def test_flags_limit_without_order():
    findings = AntiPatternAnalyzer(detectors=[UnorderedLimitDetector()]).analyze(
        [_q("SELECT * FROM t LIMIT 10")]
    )
    assert [f.code for f in findings] == ["UNORDERED_LIMIT"]


def test_ignores_limit_with_order():
    findings = AntiPatternAnalyzer(detectors=[UnorderedLimitDetector()]).analyze(
        [_q("SELECT * FROM t ORDER BY id LIMIT 10")]
    )
    assert findings == []
```

That's the whole loop: write, register, template, test. Adding an
execution-plan detector (under `analyzer/detectors/`) follows the same pattern
with the `PlanDetector` protocol and `analyzer/plan_analyzer.py`'s
`default_detectors()`.

## Submitting changes

- Keep changes conceptually small and preserve backward compatibility.
- Run `pytest -q` (and the integration suite if you touched database code).
- Update the relevant doc in the same change — docs are versioned with the code,
  and `tests/test_doc_examples.py` verifies the CLI examples still run.