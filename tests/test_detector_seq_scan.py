"""Unit tests for the sequential-scan detector (US6.1)."""

from __future__ import annotations

import pytest

from sqlcoach.analyzer.base import AnalysisContext, Severity
from sqlcoach.analyzer.detectors.seq_scan import SequentialScanDetector
from sqlcoach.models.execution_plan import PlanNode


@pytest.fixture
def detector() -> SequentialScanDetector:
    return SequentialScanDetector()


@pytest.fixture
def context() -> AnalysisContext:
    return AnalysisContext(seq_scan_row_threshold=10_000)


def _seq_scan(
    *, relation: str = "users", estimated_rows: int = 0, actual_rows: int | None = None
) -> PlanNode:
    return PlanNode(
        node_type="Seq Scan",
        relation_name=relation,
        estimated_cost=1234.5,
        estimated_rows=estimated_rows,
        actual_rows=actual_rows,
    )


class TestFiresOnLargeScans:
    def test_flags_large_scan_confirmed_by_actual_rows_as_high(
        self, detector: SequentialScanDetector, context: AnalysisContext
    ) -> None:
        node = _seq_scan(estimated_rows=9_000, actual_rows=500_000)

        findings = detector.detect(node, context)

        assert len(findings) == 1
        assert findings[0].code == "SEQ_SCAN_LARGE_TABLE"
        assert findings[0].detector == "sequential_scan"
        assert findings[0].severity is Severity.HIGH
        assert findings[0].relation_name == "users"
        assert findings[0].metrics["rows_scanned"] == 500_000
        assert findings[0].metrics["threshold"] == 10_000

    def test_estimate_only_scan_is_medium_severity(
        self, detector: SequentialScanDetector, context: AnalysisContext
    ) -> None:
        # Plan-only EXPLAIN (no ANALYZE): actual_rows is None, so the
        # estimate is used and the signal is weaker.
        node = _seq_scan(estimated_rows=250_000, actual_rows=None)

        findings = detector.detect(node, context)

        assert len(findings) == 1
        assert findings[0].severity is Severity.MEDIUM
        assert findings[0].metrics["rows_scanned"] == 250_000

    def test_fires_exactly_at_the_threshold(
        self, detector: SequentialScanDetector, context: AnalysisContext
    ) -> None:
        node = _seq_scan(actual_rows=10_000)
        assert len(detector.detect(node, context)) == 1


class TestDoesNotFire:
    def test_small_scan_is_not_flagged(
        self, detector: SequentialScanDetector, context: AnalysisContext
    ) -> None:
        node = _seq_scan(actual_rows=9_999)
        assert detector.detect(node, context) == []

    def test_index_scan_is_never_flagged(
        self, detector: SequentialScanDetector, context: AnalysisContext
    ) -> None:
        node = PlanNode(
            node_type="Index Scan",
            relation_name="users",
            estimated_cost=8.0,
            estimated_rows=1,
            actual_rows=5_000_000,
        )
        assert detector.detect(node, context) == []

    def test_actual_rows_take_precedence_over_a_large_estimate(
        self, detector: SequentialScanDetector, context: AnalysisContext
    ) -> None:
        # Planner badly over-estimated; reality is tiny. No finding.
        node = _seq_scan(estimated_rows=10_000_000, actual_rows=42)
        assert detector.detect(node, context) == []


class TestThresholdIsConfigurable:
    def test_lower_threshold_flags_a_previously_ignored_scan(
        self, detector: SequentialScanDetector
    ) -> None:
        node = _seq_scan(actual_rows=500)
        strict = AnalysisContext(seq_scan_row_threshold=100)
        assert len(detector.detect(node, strict)) == 1

    def test_higher_threshold_ignores_a_previously_flagged_scan(
        self, detector: SequentialScanDetector
    ) -> None:
        node = _seq_scan(actual_rows=50_000)
        lax = AnalysisContext(seq_scan_row_threshold=1_000_000)
        assert detector.detect(node, lax) == []


class TestRelationNameHandling:
    def test_scan_without_a_relation_name_still_reports(
        self, detector: SequentialScanDetector, context: AnalysisContext
    ) -> None:
        node = PlanNode(
            node_type="Seq Scan",
            relation_name=None,
            estimated_cost=1.0,
            estimated_rows=0,
            actual_rows=20_000,
        )
        findings = detector.detect(node, context)
        assert len(findings) == 1
        assert findings[0].relation_name is None