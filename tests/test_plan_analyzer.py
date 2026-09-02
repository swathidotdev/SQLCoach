"""Unit tests for sqlcoach.analyzer.plan_analyzer."""

from __future__ import annotations

from sqlcoach.analyzer.base import AnalysisContext, Finding, Severity
from sqlcoach.analyzer.plan_analyzer import PlanAnalyzer, default_detectors
from sqlcoach.models.execution_plan import ExecutionPlan, PlanNode


def _leaf(node_type: str, relation: str) -> PlanNode:
    return PlanNode(
        node_type=node_type,
        relation_name=relation,
        estimated_cost=1.0,
        estimated_rows=1,
    )


class _RecordingDetector:
    """A detector that emits one finding per visited node, tagging the
    order in which it was visited -- used to assert traversal order.
    """

    name = "recording"

    def __init__(self) -> None:
        self.visit_order: list[str] = []

    def detect(self, node: PlanNode, context: AnalysisContext) -> list[Finding]:
        label = node.relation_name or node.node_type
        self.visit_order.append(label)
        return [
            Finding(
                code="VISITED",
                detector=self.name,
                severity=Severity.LOW,
                summary=f"visited {label}",
                node_type=node.node_type,
                relation_name=node.relation_name,
            )
        ]


def _context() -> AnalysisContext:
    return AnalysisContext(seq_scan_row_threshold=10_000)


class TestTraversal:
    def test_visits_every_node_once(self) -> None:
        plan = ExecutionPlan(
            root=PlanNode(
                node_type="Hash Join",
                estimated_cost=10.0,
                estimated_rows=5,
                children=(_leaf("Seq Scan", "a"), _leaf("Index Scan", "b")),
            )
        )
        recorder = _RecordingDetector()

        PlanAnalyzer(detectors=[recorder]).analyze(plan, _context())

        assert recorder.visit_order == ["Hash Join", "a", "b"]

    def test_preorder_left_to_right_on_a_deeper_tree(self) -> None:
        plan = ExecutionPlan(
            root=PlanNode(
                node_type="Nested Loop",
                estimated_cost=20.0,
                estimated_rows=5,
                children=(
                    PlanNode(
                        node_type="Hash Join",
                        estimated_cost=10.0,
                        estimated_rows=5,
                        children=(_leaf("Seq Scan", "a"), _leaf("Seq Scan", "b")),
                    ),
                    _leaf("Index Scan", "c"),
                ),
            )
        )
        recorder = _RecordingDetector()

        PlanAnalyzer(detectors=[recorder]).analyze(plan, _context())

        assert recorder.visit_order == ["Nested Loop", "Hash Join", "a", "b", "c"]

    def test_handles_pathologically_deep_plans_without_recursion_error(self) -> None:
        # An iterative walk has no call-stack depth tied to plan depth,
        # so this must simply complete (NFR-3.1).
        node = _leaf("Seq Scan", "leaf")
        for _ in range(5_000):
            node = PlanNode(
                node_type="Nested Loop",
                estimated_cost=1.0,
                estimated_rows=1,
                children=(node,),
            )
        plan = ExecutionPlan(root=node)
        recorder = _RecordingDetector()

        PlanAnalyzer(detectors=[recorder]).analyze(plan, _context())

        assert len(recorder.visit_order) == 5_001


class TestDetectorComposition:
    def test_runs_detectors_in_registration_order(self) -> None:
        plan = ExecutionPlan(root=_leaf("Seq Scan", "a"))

        class First:
            name = "first"

            def detect(self, node: PlanNode, context: AnalysisContext) -> list[Finding]:
                return [Finding(code="A", detector="first", severity=Severity.LOW,
                                summary="a", node_type=node.node_type)]

        class Second:
            name = "second"

            def detect(self, node: PlanNode, context: AnalysisContext) -> list[Finding]:
                return [Finding(code="B", detector="second", severity=Severity.LOW,
                                summary="b", node_type=node.node_type)]

        findings = PlanAnalyzer(detectors=[First(), Second()]).analyze(plan, _context())

        assert [f.code for f in findings] == ["A", "B"]

    def test_a_new_detector_needs_no_changes_to_the_analyzer(self) -> None:
        # OCP: the analyzer accepts any conforming detector without
        # modification. Adding one is purely additive.
        class BitmapHeapScanDetector:
            name = "bitmap_heap_scan"

            def detect(self, node: PlanNode, context: AnalysisContext) -> list[Finding]:
                if node.node_type != "Bitmap Heap Scan":
                    return []
                return [Finding(code="BITMAP", detector=self.name, severity=Severity.LOW,
                                summary="bitmap", node_type=node.node_type)]

        plan = ExecutionPlan(root=_leaf("Bitmap Heap Scan", "t"))
        findings = PlanAnalyzer(detectors=[BitmapHeapScanDetector()]).analyze(plan, _context())

        assert [f.code for f in findings] == ["BITMAP"]


class TestDefaultRegistry:
    def test_default_analyzer_includes_the_sequential_scan_detector(self) -> None:
        names = {d.name for d in default_detectors()}
        assert "sequential_scan" in names

    def test_default_constructor_uses_the_default_registry(self) -> None:
        analyzer = PlanAnalyzer()
        assert len(analyzer.detectors) == len(default_detectors())