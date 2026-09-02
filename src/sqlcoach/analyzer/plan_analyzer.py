"""Execution-plan analyzer.

Walks an `ExecutionPlan` tree once and runs every registered
`PlanDetector` against each node, collecting their `Finding` objects
into a single flat list (FR-3.4). The analyzer owns traversal;
detectors stay focused on single-node logic.

The tree is walked *iteratively* with an explicit stack rather than
recursively. This is what satisfies NFR-3.1 (deeply nested, multi-way
join plans must not raise) by construction -- there is no call-stack
depth tied to plan depth, so no artificial depth limit is needed here
(unlike `plan_json_parser`, whose recursive construction required an
explicit guard).

Traversal order is deterministic: pre-order depth-first with children
visited in their original left-to-right order, and detectors run in
registration order. Deterministic output matters for testability and
for the Sprint 10 `compare` command (NFR-4.3).
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlcoach.analyzer.base import AnalysisContext, Finding, PlanDetector
from sqlcoach.analyzer.detectors.cardinality import CardinalityMisestimationDetector
from sqlcoach.analyzer.detectors.expensive_sort import ExpensiveSortDetector
from sqlcoach.analyzer.detectors.join_strategy import JoinStrategyDetector
from sqlcoach.analyzer.detectors.seq_scan import SequentialScanDetector
from sqlcoach.models.execution_plan import ExecutionPlan, PlanNode


def default_detectors() -> tuple[PlanDetector, ...]:
    """Return the default set of plan detectors, in run order.

    This is the single registration point for detectors. Adding a new
    detector means one import and one entry here; nothing else changes
    (OCP).
    """
    return (
        SequentialScanDetector(),
        JoinStrategyDetector(),
        ExpensiveSortDetector(),
        CardinalityMisestimationDetector(),
    )


class PlanAnalyzer:
    """Runs a set of detectors across every node of an execution plan.

    A single instance is reusable across many plans and is stateless
    between calls -- all per-run inputs (the plan and the tuned
    thresholds) are passed to `analyze()`.
    """

    def __init__(self, detectors: Sequence[PlanDetector] | None = None) -> None:
        """Create an analyzer.

        Args:
            detectors: The detectors to run, in order. Defaults to
                `default_detectors()`. Injecting a custom sequence
                keeps the analyzer testable in isolation and lets
                callers run a focused subset.
        """
        self._detectors: tuple[PlanDetector, ...] = (
            tuple(detectors) if detectors is not None else default_detectors()
        )

    @property
    def detectors(self) -> tuple[PlanDetector, ...]:
        """The detectors this analyzer will run, in order."""
        return self._detectors

    def analyze(self, plan: ExecutionPlan, context: AnalysisContext) -> list[Finding]:
        """Analyze an execution plan and return all detected findings.

        Args:
            plan: The parsed EXPLAIN plan to inspect.
            context: Tuned thresholds for this run.

        Returns:
            All findings from all detectors across all nodes, in
            deterministic pre-order traversal order (and, within a
            node, detector-registration order).
        """
        findings: list[Finding] = []
        # Explicit stack, seeded with the root. Children are pushed in
        # reverse so they pop in original left-to-right order, giving a
        # stable pre-order walk.
        stack: list[PlanNode] = [plan.root]
        while stack:
            node = stack.pop()
            for detector in self._detectors:
                findings.extend(detector.detect(node, context))
            stack.extend(reversed(node.children))
        return findings