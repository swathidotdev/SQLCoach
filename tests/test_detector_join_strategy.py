"""Unit tests for the join-strategy detector (US6.2)."""

from __future__ import annotations

import pytest

from sqlcoach.analyzer.base import AnalysisContext, Severity
from sqlcoach.analyzer.detectors.join_strategy import JoinStrategyDetector
from sqlcoach.models.execution_plan import PlanNode


@pytest.fixture
def detector() -> JoinStrategyDetector:
    return JoinStrategyDetector()


@pytest.fixture
def context() -> AnalysisContext:
    return AnalysisContext(nested_loop_row_threshold=10_000)


def _scan(
    node_type: str, relation: str, *, estimated_rows: int = 1, actual_rows: int | None = None
) -> PlanNode:
    return PlanNode(
        node_type=node_type,
        relation_name=relation,
        estimated_cost=1.0,
        estimated_rows=estimated_rows,
        actual_rows=actual_rows,
    )


def _join(
    node_type: str,
    *,
    outer: PlanNode,
    inner: PlanNode | None = None,
    estimated_rows: int = 1,
    actual_rows: int | None = None,
) -> PlanNode:
    children = (outer,) if inner is None else (outer, inner)
    return PlanNode(
        node_type=node_type,
        estimated_cost=10.0,
        estimated_rows=estimated_rows,
        actual_rows=actual_rows,
        children=children,
    )


class TestFiresOnLargeNestedLoops:
    def test_large_nested_loop_over_seq_scan_inner_is_high(
        self, detector: JoinStrategyDetector, context: AnalysisContext
    ) -> None:
        node = _join(
            "Nested Loop",
            outer=_scan("Index Scan", "users", actual_rows=500_000),
            inner=_scan("Seq Scan", "orders", actual_rows=200),
            actual_rows=500_000,
        )

        findings = detector.detect(node, context)

        assert len(findings) == 1
        assert findings[0].code == "NESTED_LOOP_LARGE_ROWCOUNT"
        assert findings[0].detector == "join_strategy"
        assert findings[0].severity is Severity.HIGH
        assert findings[0].metrics["outer_rows"] == 500_000
        assert findings[0].metrics["threshold"] == 10_000
        assert "orders" in findings[0].summary

    def test_large_nested_loop_over_indexed_inner_is_medium(
        self, detector: JoinStrategyDetector, context: AnalysisContext
    ) -> None:
        node = _join(
            "Nested Loop",
            outer=_scan("Seq Scan", "users", actual_rows=50_000),
            inner=_scan("Index Scan", "orders", actual_rows=1),
            actual_rows=50_000,
        )

        findings = detector.detect(node, context)

        assert len(findings) == 1
        assert findings[0].severity is Severity.MEDIUM

    def test_uses_estimate_when_actual_absent(
        self, detector: JoinStrategyDetector, context: AnalysisContext
    ) -> None:
        node = _join(
            "Nested Loop",
            outer=_scan("Seq Scan", "users", estimated_rows=80_000),
            inner=_scan("Seq Scan", "orders", estimated_rows=10),
            estimated_rows=80_000,
        )

        findings = detector.detect(node, context)

        assert len(findings) == 1
        assert findings[0].metrics["outer_rows"] == 80_000
        assert "estimated" in findings[0].summary


class TestDoesNotFire:
    def test_small_nested_loop_is_not_flagged(
        self, detector: JoinStrategyDetector, context: AnalysisContext
    ) -> None:
        node = _join(
            "Nested Loop",
            outer=_scan("Index Scan", "users", actual_rows=50),
            inner=_scan("Index Scan", "orders", actual_rows=1),
            actual_rows=50,
        )
        assert detector.detect(node, context) == []

    def test_hash_join_is_never_flagged(
        self, detector: JoinStrategyDetector, context: AnalysisContext
    ) -> None:
        node = _join(
            "Hash Join",
            outer=_scan("Seq Scan", "users", actual_rows=5_000_000),
            inner=_scan("Hash", "orders", actual_rows=1_000_000),
            actual_rows=5_000_000,
        )
        assert detector.detect(node, context) == []

    def test_merge_join_is_never_flagged(
        self, detector: JoinStrategyDetector, context: AnalysisContext
    ) -> None:
        node = _join(
            "Merge Join",
            outer=_scan("Sort", "users", actual_rows=5_000_000),
            inner=_scan("Sort", "orders", actual_rows=5_000_000),
            actual_rows=5_000_000,
        )
        assert detector.detect(node, context) == []

    def test_non_join_node_is_ignored(
        self, detector: JoinStrategyDetector, context: AnalysisContext
    ) -> None:
        node = _scan("Seq Scan", "users", actual_rows=9_999_999)
        assert detector.detect(node, context) == []

    def test_nested_loop_with_no_children_is_ignored(
        self, detector: JoinStrategyDetector, context: AnalysisContext
    ) -> None:
        node = PlanNode(
            node_type="Nested Loop", estimated_cost=10.0, estimated_rows=999_999
        )
        assert detector.detect(node, context) == []


class TestThresholdIsConfigurable:
    def test_higher_threshold_ignores_a_previously_flagged_loop(
        self, detector: JoinStrategyDetector
    ) -> None:
        node = _join(
            "Nested Loop",
            outer=_scan("Seq Scan", "users", actual_rows=50_000),
            inner=_scan("Seq Scan", "orders", actual_rows=10),
            actual_rows=50_000,
        )
        lax = AnalysisContext(nested_loop_row_threshold=1_000_000)
        assert detector.detect(node, lax) == []

    def test_inner_side_missing_falls_back_to_medium(
        self, detector: JoinStrategyDetector, context: AnalysisContext
    ) -> None:
        # A single-child nested loop (unusual) still assesses the outer
        # side but has no inner node to classify, so it can't be HIGH.
        node = _join(
            "Nested Loop",
            outer=_scan("Seq Scan", "users", actual_rows=50_000),
            inner=None,
            actual_rows=50_000,
        )
        findings = detector.detect(node, context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.MEDIUM