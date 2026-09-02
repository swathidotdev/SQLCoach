"""Unit tests for the expensive-sort detector (US6.3)."""

from __future__ import annotations

import pytest

from sqlcoach.analyzer.base import AnalysisContext, Severity
from sqlcoach.analyzer.detectors.expensive_sort import ExpensiveSortDetector
from sqlcoach.models.execution_plan import PlanNode


@pytest.fixture
def detector() -> ExpensiveSortDetector:
    return ExpensiveSortDetector()


@pytest.fixture
def context() -> AnalysisContext:
    return AnalysisContext()


def _sort(
    *,
    node_type: str = "Sort",
    sort_key: tuple[str, ...] = ("created_at",),
    sort_method: str | None = None,
    sort_space_type: str | None = None,
    sort_space_used_kb: int | None = None,
) -> PlanNode:
    return PlanNode(
        node_type=node_type,
        estimated_cost=100.0,
        estimated_rows=1000,
        sort_key=sort_key,
        sort_method=sort_method,
        sort_space_type=sort_space_type,
        sort_space_used_kb=sort_space_used_kb,
    )


class TestFiresOnDiskSpill:
    def test_external_merge_with_disk_space_type_fires_high(
        self, detector: ExpensiveSortDetector, context: AnalysisContext
    ) -> None:
        node = _sort(
            sort_method="external merge",
            sort_space_type="Disk",
            sort_space_used_kb=45_000,
        )

        findings = detector.detect(node, context)

        assert len(findings) == 1
        assert findings[0].code == "SORT_SPILLED_TO_DISK"
        assert findings[0].detector == "expensive_sort"
        assert findings[0].severity is Severity.HIGH
        assert findings[0].metrics["sort_space_used_kb"] == 45_000
        assert "created_at" in findings[0].summary

    def test_disk_space_type_alone_is_enough(
        self, detector: ExpensiveSortDetector, context: AnalysisContext
    ) -> None:
        node = _sort(sort_method=None, sort_space_type="Disk", sort_space_used_kb=8_000)
        assert len(detector.detect(node, context)) == 1

    def test_external_method_alone_is_enough(
        self, detector: ExpensiveSortDetector, context: AnalysisContext
    ) -> None:
        # Method name signals the spill even if space type is absent.
        node = _sort(sort_method="external sort", sort_space_type=None)
        assert len(detector.detect(node, context)) == 1

    def test_incremental_sort_can_spill(
        self, detector: ExpensiveSortDetector, context: AnalysisContext
    ) -> None:
        node = _sort(
            node_type="Incremental Sort",
            sort_method="external merge",
            sort_space_type="Disk",
            sort_space_used_kb=1_000,
        )
        assert len(detector.detect(node, context)) == 1

    def test_summary_handles_missing_space_used(
        self, detector: ExpensiveSortDetector, context: AnalysisContext
    ) -> None:
        node = _sort(sort_method="external merge", sort_space_type="Disk")
        findings = detector.detect(node, context)
        assert len(findings) == 1
        assert "sort_space_used_kb" not in findings[0].metrics


class TestDoesNotFire:
    def test_in_memory_quicksort_is_not_flagged(
        self, detector: ExpensiveSortDetector, context: AnalysisContext
    ) -> None:
        node = _sort(
            sort_method="quicksort", sort_space_type="Memory", sort_space_used_kb=512
        )
        assert detector.detect(node, context) == []

    def test_top_n_heapsort_in_memory_is_not_flagged(
        self, detector: ExpensiveSortDetector, context: AnalysisContext
    ) -> None:
        node = _sort(
            sort_method="top-N heapsort", sort_space_type="Memory", sort_space_used_kb=64
        )
        assert detector.detect(node, context) == []

    def test_plan_only_sort_without_runtime_info_is_not_flagged(
        self, detector: ExpensiveSortDetector, context: AnalysisContext
    ) -> None:
        # No ANALYZE: no sort method or space type is known, so a spill
        # cannot be asserted. The detector stays silent.
        node = _sort(sort_method=None, sort_space_type=None, sort_space_used_kb=None)
        assert detector.detect(node, context) == []

    def test_non_sort_node_is_ignored(
        self, detector: ExpensiveSortDetector, context: AnalysisContext
    ) -> None:
        node = PlanNode(
            node_type="Seq Scan",
            relation_name="users",
            estimated_cost=1.0,
            estimated_rows=1,
            sort_space_type="Disk",  # nonsensical on a scan; must be ignored anyway
        )
        assert detector.detect(node, context) == []