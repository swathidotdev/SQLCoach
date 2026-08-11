"""Unit tests for sqlcoach.models.execution_plan."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sqlcoach.models.execution_plan import ExecutionPlan, PlanNode


class TestPlanNodeConstruction:
    def test_leaf_node(self) -> None:
        node = PlanNode(
            node_type="Seq Scan",
            relation_name="users",
            estimated_cost=1250.0,
            estimated_rows=50000,
            actual_rows=49800,
            actual_time_ms=42.3,
        )
        assert node.node_type == "Seq Scan"
        assert node.children == ()

    def test_nested_join_node(self) -> None:
        left = PlanNode(node_type="Seq Scan", relation_name="orders", estimated_cost=100, estimated_rows=1000)
        right = PlanNode(node_type="Index Scan", relation_name="users", estimated_cost=10, estimated_rows=1)
        join = PlanNode(
            node_type="Hash Join",
            estimated_cost=500,
            estimated_rows=1000,
            children=(left, right),
        )
        assert len(join.children) == 2
        assert join.children[0].relation_name == "orders"


class TestPlanNodeValidation:
    def test_negative_estimated_cost_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PlanNode(node_type="Seq Scan", estimated_cost=-1, estimated_rows=0)

    def test_negative_estimated_rows_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PlanNode(node_type="Seq Scan", estimated_cost=1, estimated_rows=-5)

    def test_unknown_field_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PlanNode(node_type="Seq Scan", estimated_cost=1, estimated_rows=0, bogus="oops")


class TestDeepNesting:
    def test_handles_a_deeply_nested_plan_without_recursion_error(self) -> None:
        current = PlanNode(node_type="Seq Scan", estimated_cost=1, estimated_rows=1)
        for _ in range(200):
            current = PlanNode(
                node_type="Nested Loop",
                estimated_cost=1,
                estimated_rows=1,
                children=(current,),
            )
        depth = 0
        node: PlanNode | None = current
        while node is not None and node.children:
            depth += 1
            node = node.children[0]
        assert depth == 200


class TestExecutionPlanConstruction:
    def test_wraps_root_node_with_timing_metadata(self) -> None:
        root = PlanNode(node_type="Seq Scan", relation_name="users", estimated_cost=100, estimated_rows=1000)
        plan = ExecutionPlan(root=root, planning_time_ms=0.5, execution_time_ms=42.0)
        assert plan.root.relation_name == "users"
        assert plan.planning_time_ms == 0.5

    def test_timing_metadata_is_optional(self) -> None:
        root = PlanNode(node_type="Seq Scan", estimated_cost=1, estimated_rows=1)
        plan = ExecutionPlan(root=root)
        assert plan.planning_time_ms is None
        assert plan.execution_time_ms is None


class TestImmutability:
    def test_plan_node_is_frozen(self) -> None:
        node = PlanNode(node_type="Seq Scan", estimated_cost=1, estimated_rows=1)
        with pytest.raises(ValidationError):
            node.node_type = "Index Scan"  # type: ignore[misc]

    def test_execution_plan_is_frozen(self) -> None:
        root = PlanNode(node_type="Seq Scan", estimated_cost=1, estimated_rows=1)
        plan = ExecutionPlan(root=root)
        with pytest.raises(ValidationError):
            plan.execution_time_ms = 99.0  # type: ignore[misc]