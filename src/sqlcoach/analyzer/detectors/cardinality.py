"""Cardinality-misestimation detector (US6.4, FR-3.4.4).

Flags scan nodes where the planner's estimated row count and the
measured actual row count diverge by a large factor. Such a divergence
means the planner is costing plans from stale or missing table
statistics, which in turn leads it to pick poor join orders, join
strategies, or scan methods -- so the mismatch is worth surfacing even
before any single downstream node looks slow.

Scope: this detector fires on *scan* nodes only. Estimated-vs-actual
divergence there points squarely at base-table statistics, whose fix
is concrete and actionable ("run ANALYZE on the table", or raise its
statistics target). Divergence at a join or aggregate node is usually
either a *consequence* of a scan-level misestimate (already reported at
the scan) or a column-correlation problem needing extended statistics
-- a different root cause and fix, deliberately left to a future
detector rather than folded in here and reported as noise up the tree.

Both `Plan Rows` and `Actual Rows` are per-loop values in PostgreSQL,
so they are directly comparable without needing the loop count.
Requires ANALYZE (actual rows must be present); a plan-only EXPLAIN
carries no actuals and is silently skipped.
"""

from __future__ import annotations

from sqlcoach.analyzer.base import AnalysisContext, Finding, PlanDetector, Severity
from sqlcoach.models.execution_plan import PlanNode

#: Scan nodes whose row estimates are driven by base-table statistics.
_SCAN_NODE_TYPES = frozenset(
    {"Seq Scan", "Index Scan", "Index Only Scan", "Bitmap Heap Scan"}
)

_CODE = "CARDINALITY_MISESTIMATION"


class CardinalityMisestimationDetector(PlanDetector):
    """Detects scan nodes whose estimated and actual row counts diverge
    beyond a configurable ratio.
    """

    name = "cardinality_misestimation"

    def detect(self, node: PlanNode, context: AnalysisContext) -> list[Finding]:
        if node.node_type not in _SCAN_NODE_TYPES:
            return []

        # Divergence can only be measured when ANALYZE supplied actuals.
        if node.actual_rows is None:
            return []

        estimated = node.estimated_rows
        actual = node.actual_rows

        larger = max(estimated, actual)
        smaller = min(estimated, actual)

        # Suppress noise from tiny absolute counts: a 1-vs-12 mismatch is
        # a 12x ratio but performance-irrelevant.
        if larger < context.cardinality_min_rows:
            return []

        # Guard division when a side is zero (planner or reality reported
        # no rows). Treating the smaller side as at least 1 keeps the
        # ratio finite and meaningful.
        ratio = larger / max(smaller, 1)
        if ratio < context.cardinality_misestimation_ratio:
            return []

        # Under-estimation (actual far exceeds estimate) is the more
        # dangerous direction: the planner, expecting few rows, tends to
        # choose nested loops and other strategies that degrade badly
        # when the true count is large. Over-estimation is still worth
        # flagging but is the softer signal.
        underestimated = actual > estimated
        severity = Severity.HIGH if underestimated else Severity.MEDIUM
        direction = "under-estimated" if underestimated else "over-estimated"
        relation = node.relation_name or "an unnamed relation"

        return [
            Finding(
                code=_CODE,
                detector=self.name,
                severity=severity,
                summary=(
                    f"Planner {direction} rows for {relation}: estimated "
                    f"{estimated:,} but {actual:,} actually returned (~{ratio:.0f}x off). "
                    f"Stale or missing statistics are the usual cause; running ANALYZE "
                    f"on the table, or raising its statistics target, would sharpen the "
                    f"estimate and the plans built on it"
                ),
                node_type=node.node_type,
                relation_name=node.relation_name,
                metrics={
                    "estimated_rows": estimated,
                    "actual_rows": actual,
                    "ratio": round(ratio, 2),
                    "threshold": context.cardinality_misestimation_ratio,
                },
            )
        ]