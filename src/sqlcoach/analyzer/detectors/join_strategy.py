"""Join-strategy detector (US6.2, FR-3.4.2).

Identifies the three PostgreSQL join strategies -- nested loop, hash,
and merge -- and flags the one that turns pathological at scale: a
*nested loop* driven by a large number of outer rows. A nested loop
executes its inner side once per outer row, so it is optimal when the
outer input is tiny and quadratic when it is large. Hash and merge
joins, by contrast, scale well on large inputs, so recognizing them is
how the detector knows a large nested loop is the outlier worth
flagging -- they themselves are never reported as issues.

This keeps the findings list actionable: `Finding` is an *issue*
contract that the recommendation engine (Sprint 9) turns into advice,
so a healthy hash join must not produce one.
"""

from __future__ import annotations

from typing import Optional

from sqlcoach.analyzer.base import AnalysisContext, Finding, PlanDetector, Severity
from sqlcoach.models.execution_plan import PlanNode

_NESTED_LOOP = "Nested Loop"
_HASH_JOIN = "Hash Join"
_MERGE_JOIN = "Merge Join"
_JOIN_NODE_TYPES = frozenset({_NESTED_LOOP, _HASH_JOIN, _MERGE_JOIN})

_SEQ_SCAN = "Seq Scan"

_CODE = "NESTED_LOOP_LARGE_ROWCOUNT"


def _row_count(node: PlanNode) -> int:
    """Return a node's measured row count, falling back to the estimate.

    For the *outer* child of a nested loop this equals the number of
    inner-side iterations, since the outer side runs exactly once.
    """
    return node.actual_rows if node.actual_rows is not None else node.estimated_rows


class JoinStrategyDetector(PlanDetector):
    """Detects nested-loop joins whose outer row count is large enough
    to make the strategy a likely bottleneck.
    """

    name = "join_strategy"

    def detect(self, node: PlanNode, context: AnalysisContext) -> list[Finding]:
        if node.node_type not in _JOIN_NODE_TYPES:
            return []

        # Hash and merge joins are recognized here but scale acceptably
        # on large inputs, so they are never flagged as issues.
        if node.node_type != _NESTED_LOOP:
            return []

        # A well-formed join has an outer (first) and inner (second)
        # child. Guard against a malformed node with no children rather
        # than indexing blindly.
        if not node.children:
            return []

        outer = node.children[0]
        inner: Optional[PlanNode] = node.children[1] if len(node.children) > 1 else None

        iterations = _row_count(outer)
        if iterations < context.nested_loop_row_threshold:
            return []

        # Severity is driven by how expensive each iteration is, not by
        # measurement source (that's carried in metrics for Sprint 9's
        # confidence layer). A nested loop whose inner side is a
        # sequential scan re-scans a table on every iteration -- the
        # genuine O(n*m) disaster, hence HIGH. An indexed inner side may
        # still be acceptable, so a large-but-indexed nested loop is a
        # softer MEDIUM signal worth review rather than a certain fault.
        inner_is_seq_scan = inner is not None and inner.node_type == _SEQ_SCAN
        severity = Severity.HIGH if inner_is_seq_scan else Severity.MEDIUM
        iterations_are_measured = outer.actual_rows is not None
        source = "actual" if iterations_are_measured else "estimated"

        if inner_is_seq_scan:
            inner_relation = (inner.relation_name if inner else None) or "a table"
            summary = (
                f"Nested loop runs its inner side ~{iterations:,} times ({source}), "
                f"re-scanning {inner_relation} sequentially each time; a hash or merge "
                f"join, or an index on the inner side, would likely scale better"
            )
        else:
            summary = (
                f"Nested loop runs its inner side ~{iterations:,} times ({source}); "
                f"review whether a hash or merge join would scale better here"
            )

        return [
            Finding(
                code=_CODE,
                detector=self.name,
                severity=severity,
                summary=summary,
                node_type=node.node_type,
                relation_name=node.relation_name,
                metrics={
                    "outer_rows": iterations,
                    "output_rows": _row_count(node),
                    "threshold": context.nested_loop_row_threshold,
                },
            )
        ]