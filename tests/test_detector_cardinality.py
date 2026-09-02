"""Unit tests for the cardinality-misestimation detector (US6.4)."""

from __future__ import annotations

import pytest

from sqlcoach.analyzer.base import AnalysisContext, Severity
from sqlcoach.analyzer.detectors.cardinality import CardinalityMisestimationDetector
from sqlcoach.models.execution_plan import PlanNode


@pytest.fixture
def detector() -> CardinalityMisestimationDetector:
    return CardinalityMisestimationDetector()


@pytest.fixture
def context() -> AnalysisContext:
    return AnalysisContext(
        cardinality_misestimation_ratio=10.0, cardinality_min_rows=100
    )


def _scan(
    *,
    node_type: str = "Seq Scan",
    relation: str = "orders",
    estimated_rows: int,
    actual_rows: int | None,
) -> PlanNode:
    return PlanNode(
        node_type=node_type,
        relation_name=relation,
        estimated_cost=100.0,
        estimated_rows=estimated_rows,
        actual_rows=actual_rows,
    )


class TestFiresOnMisestimation:
    def test_underestimate_is_high_severity(
        self, detector: CardinalityMisestimationDetector, context: AnalysisContext
    ) -> None:
        node = _scan(estimated_rows=100, actual_rows=100_000)

        findings = detector.detect(node, context)

        assert len(findings) == 1
        assert findings[0].code == "CARDINALITY_MISESTIMATION"
        assert findings[0].detector == "cardinality_misestimation"
        assert findings[0].severity is Severity.HIGH
        assert findings[0].metrics["estimated_rows"] == 100
        assert findings[0].metrics["actual_rows"] == 100_000
        assert findings[0].metrics["ratio"] == 1000.0
        assert "under-estimated" in findings[0].summary

    def test_overestimate_is_medium_severity(
        self, detector: CardinalityMisestimationDetector, context: AnalysisContext
    ) -> None:
        node = _scan(estimated_rows=500_000, actual_rows=200)

        findings = detector.detect(node, context)

        assert len(findings) == 1
        assert findings[0].severity is Severity.MEDIUM
        assert "over-estimated" in findings[0].summary

    def test_fires_across_scan_node_types(
        self, detector: CardinalityMisestimationDetector, context: AnalysisContext
    ) -> None:
        for node_type in ("Seq Scan", "Index Scan", "Index Only Scan", "Bitmap Heap Scan"):
            node = _scan(node_type=node_type, estimated_rows=100, actual_rows=50_000)
            assert len(detector.detect(node, context)) == 1, node_type

    def test_handles_zero_estimate_without_dividing_by_zero(
        self, detector: CardinalityMisestimationDetector, context: AnalysisContext
    ) -> None:
        node = _scan(estimated_rows=0, actual_rows=5_000)
        findings = detector.detect(node, context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.HIGH


class TestDoesNotFire:
    def test_accurate_estimate_is_not_flagged(
        self, detector: CardinalityMisestimationDetector, context: AnalysisContext
    ) -> None:
        node = _scan(estimated_rows=10_000, actual_rows=11_000)
        assert detector.detect(node, context) == []

    def test_tiny_absolute_counts_are_suppressed_by_the_floor(
        self, detector: CardinalityMisestimationDetector, context: AnalysisContext
    ) -> None:
        # 1 vs 12 is a 12x ratio but far below the 100-row floor.
        node = _scan(estimated_rows=1, actual_rows=12)
        assert detector.detect(node, context) == []

    def test_plan_only_scan_without_actuals_is_not_flagged(
        self, detector: CardinalityMisestimationDetector, context: AnalysisContext
    ) -> None:
        node = _scan(estimated_rows=100, actual_rows=None)
        assert detector.detect(node, context) == []

    def test_non_scan_node_is_ignored(
        self, detector: CardinalityMisestimationDetector, context: AnalysisContext
    ) -> None:
        # A join can misestimate too, but that's a different root cause
        # (correlation / extended stats), deliberately out of scope here.
        node = PlanNode(
            node_type="Hash Join",
            estimated_cost=10.0,
            estimated_rows=100,
            actual_rows=100_000,
        )
        assert detector.detect(node, context) == []


class TestConfigurable:
    def test_ratio_threshold_is_honored(
        self, detector: CardinalityMisestimationDetector
    ) -> None:
        node = _scan(estimated_rows=1_000, actual_rows=5_000)  # 5x
        strict = AnalysisContext(
            cardinality_misestimation_ratio=3.0, cardinality_min_rows=100
        )
        lax = AnalysisContext(
            cardinality_misestimation_ratio=100.0, cardinality_min_rows=100
        )
        assert len(detector.detect(node, strict)) == 1
        assert detector.detect(node, lax) == []

    def test_floor_can_be_disabled(
        self, detector: CardinalityMisestimationDetector
    ) -> None:
        node = _scan(estimated_rows=1, actual_rows=50)
        no_floor = AnalysisContext(
            cardinality_misestimation_ratio=10.0, cardinality_min_rows=0
        )
        assert len(detector.detect(node, no_floor)) == 1