"""Performance test at scale (Sprint 12, US12.4, FR-5.4).

Runs a 10,000+ query synthetic workload through parse -> anti-pattern
analysis -> recommendation engine. The timing assertion is bounded and
generous (catches a catastrophic scalability regression, never flaky),
and the test also asserts correctness at scale -- all statements parse
and every anti-pattern type is still detected in a large workload.

Marked `performance`; skipped unless SQLCOACH_RUN_PERF is set.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from sqlcoach.advisor.anti_patterns.analyzer import (
    AntiPatternAnalyzer,
    default_detectors,
)
from sqlcoach.advisor.recommendation_engine import RecommendationEngine
from sqlcoach.parser.sql_file_parser import SqlFileParser

pytestmark = pytest.mark.performance

_STATEMENT_COUNT = 10_000
_TIME_BUDGET_SECONDS = 60.0  # generous: ~10x observed headroom, non-flaky


def _write_workload(path: Path) -> None:
    lines = [f"SELECT id, total FROM orders WHERE user_id = {i};" for i in range(9_700)]
    lines += [f"SELECT * FROM users WHERE email = 'u{i}@x.com';" for i in range(150)]
    lines += [f"SELECT name FROM customers WHERE name LIKE '%term{i}';" for i in range(100)]
    lines += ["SELECT id FROM logs ORDER BY RANDOM();" for _ in range(50)]
    path.write_text("\n".join(lines), encoding="utf-8")


def test_large_workload_within_time_budget_and_correct(tmp_path: Path) -> None:
    workload = tmp_path / "workload.sql"
    _write_workload(workload)

    start = time.perf_counter()
    queries = SqlFileParser().parse(workload)
    findings = AntiPatternAnalyzer(
        detectors=default_detectors(n_plus_one_min_occurrences=5)
    ).analyze(queries)
    recommendations = RecommendationEngine().generate(anti_pattern_findings=findings)
    elapsed = time.perf_counter() - start

    # Correctness at scale.
    assert len(queries) == _STATEMENT_COUNT
    codes = {f.code for f in findings}
    assert codes == {
        "SELECT_STAR",
        "LEADING_WILDCARD_LIKE",
        "ORDER_BY_RANDOM",
        "N_PLUS_ONE",
    }
    assert recommendations

    # Scalability guard (bounded, generous).
    assert elapsed < _TIME_BUDGET_SECONDS, (
        f"{_STATEMENT_COUNT} queries took {elapsed:.1f}s, over the "
        f"{_TIME_BUDGET_SECONDS}s budget"
    )