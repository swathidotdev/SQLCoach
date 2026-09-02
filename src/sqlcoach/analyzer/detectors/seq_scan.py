"""Sequential-scan detector (US6.1, FR-3.4.1).

Flags sequential scans that read a large number of rows -- the classic
signal that a table is being scanned end-to-end where an index could
turn the access into a targeted lookup. The row-count threshold is
configurable (`AnalysisContext.seq_scan_row_threshold`).
"""

from __future__ import annotations

from sqlcoach.analyzer.base import AnalysisContext, Finding, PlanDetector, Severity
from sqlcoach.models.execution_plan import PlanNode

#: PostgreSQL node type for a full-table scan. Parallel sequential
#: scans carry this same node type (parallelism is a separate flag,
#: not a distinct node type), so this single string covers both.
_SEQ_SCAN_NODE_TYPE = "Seq Scan"

_CODE = "SEQ_SCAN_LARGE_TABLE"


class SequentialScanDetector(PlanDetector):
    """Detects sequential scans over row counts above a threshold."""

    name = "sequential_scan"

    def detect(self, node: PlanNode, context: AnalysisContext) -> list[Finding]:
        if node.node_type != _SEQ_SCAN_NODE_TYPE:
            return []

        # Prefer the measured row count when ANALYZE was used; fall back
        # to the planner's estimate for a plan-only EXPLAIN. Note that
        # PostgreSQL reports actual rows *per loop*, so a scan on the
        # inner side of a nested loop reflects rows per iteration, not
        # the grand total -- an accepted simplification here, documented
        # so a later loop-aware refinement is a conscious change.
        rows_are_measured = node.actual_rows is not None
        rows = node.actual_rows if rows_are_measured else node.estimated_rows

        if rows < context.seq_scan_row_threshold:
            return []

        # Evidence strength drives severity, foreshadowing Sprint 9's
        # confidence scoring: a scan confirmed by real execution rows is
        # a firmer signal than one resting on a planner estimate.
        severity = Severity.HIGH if rows_are_measured else Severity.MEDIUM
        source = "actual" if rows_are_measured else "estimated"
        relation = node.relation_name or "an unnamed relation"

        return [
            Finding(
                code=_CODE,
                detector=self.name,
                severity=severity,
                summary=(
                    f"Sequential scan on {relation} reads {rows:,} rows "
                    f"({source}), at or above the {context.seq_scan_row_threshold:,}-row "
                    f"threshold"
                ),
                node_type=node.node_type,
                relation_name=node.relation_name,
                metrics={
                    "rows_scanned": rows,
                    "threshold": context.seq_scan_row_threshold,
                },
            )
        ]