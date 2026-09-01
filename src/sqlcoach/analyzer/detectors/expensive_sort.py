"""Expensive-sort detector (US6.3, FR-3.4.3).

Flags sort operations that spilled to disk. When a sort's working set
exceeds `work_mem`, PostgreSQL falls back from an in-memory sort
(quicksort / top-N heapsort) to an external merge sort on disk,
incurring extra I/O. That spill is the signal this detector reports.

Disk spill is a *runtime* fact: `Sort Method` and `Sort Space Type`
appear only when the plan was produced with ANALYZE. A plan-only
EXPLAIN carries no spill information, so this detector simply never
fires on one -- correctly, since the spill genuinely cannot be known
in advance. The trigger is binary (spilled or not), so there is no
threshold to configure; an in-memory sort is never flagged.
"""

from __future__ import annotations

from sqlcoach.analyzer.base import AnalysisContext, Finding, PlanDetector, Severity
from sqlcoach.models.execution_plan import PlanNode

#: Both plain and incremental sorts can spill to disk. Incremental Sort
#: (PG13+) usually reports space per group rather than at the node's top
#: level, so its top-level spill fields may be absent -- in which case
#: this detector conservatively stays silent rather than guessing.
_SORT_NODE_TYPES = frozenset({"Sort", "Incremental Sort"})

_DISK = "disk"
_EXTERNAL = "external"

_CODE = "SORT_SPILLED_TO_DISK"


class ExpensiveSortDetector(PlanDetector):
    """Detects sort nodes that spilled from memory to disk."""

    name = "expensive_sort"

    def detect(self, node: PlanNode, context: AnalysisContext) -> list[Finding]:
        if node.node_type not in _SORT_NODE_TYPES:
            return []

        if not self._spilled_to_disk(node):
            return []

        # A disk spill is a measured runtime event, not an estimate, so
        # it is reported at HIGH severity -- consistent with the
        # analyzer's convention that confirmed issues outrank
        # estimate-only ones. The magnitude (space used) is carried in
        # metrics for Sprint 9's impact/confidence layer to weigh; a
        # marginal spill and a multi-gigabyte spill share this code but
        # differ in their metrics.
        metrics: dict[str, int | float] = {}
        if node.sort_space_used_kb is not None:
            metrics["sort_space_used_kb"] = node.sort_space_used_kb

        return [
            Finding(
                code=_CODE,
                detector=self.name,
                severity=Severity.HIGH,
                summary=self._summary(node),
                node_type=node.node_type,
                relation_name=node.relation_name,
                metrics=metrics,
            )
        ]

    @staticmethod
    def _spilled_to_disk(node: PlanNode) -> bool:
        """Return True if the sort used disk rather than staying in memory.

        Two independent signals, either sufficient: an explicit
        "Disk" space type, or a sort method PostgreSQL only uses when
        spilling (its name contains "external", e.g. "external merge").
        """
        if node.sort_space_type is not None and node.sort_space_type.lower() == _DISK:
            return True
        if node.sort_method is not None and _EXTERNAL in node.sort_method.lower():
            return True
        return False

    @staticmethod
    def _summary(node: PlanNode) -> str:
        method = node.sort_method or "an external sort"
        space = (
            f", {node.sort_space_used_kb:,} KB"
            if node.sort_space_used_kb is not None
            else ""
        )
        keys = f" on ({', '.join(node.sort_key)})" if node.sort_key else ""
        return (
            f"Sort{keys} spilled to disk ({method}{space}); it exceeded work_mem, "
            f"forcing disk I/O. Raising work_mem, or adding an index that supplies "
            f"pre-sorted output, would avoid the spill"
        )