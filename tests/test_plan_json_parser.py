"""Unit tests for sqlcoach.parser.plan_json_parser."""

from __future__ import annotations

import pytest

from sqlcoach.exceptions import ParsingError
from sqlcoach.parser.plan_json_parser import parse_explain_json


class TestSimplePlan:
    def test_parses_a_leaf_seq_scan(self) -> None:
        payload = [
            {
                "Plan": {
                    "Node Type": "Seq Scan",
                    "Relation Name": "users",
                    "Total Cost": 25.5,
                    "Plan Rows": 1500,
                    "Actual Rows": 1480,
                    "Actual Total Time": 0.045,
                },
                "Planning Time": 0.123,
                "Execution Time": 0.567,
            }
        ]

        plan = parse_explain_json(payload)

        assert plan.root.node_type == "Seq Scan"
        assert plan.root.relation_name == "users"
        assert plan.root.estimated_cost == 25.5
        assert plan.root.estimated_rows == 1500
        assert plan.root.actual_rows == 1480
        assert plan.root.actual_time_ms == 0.045
        assert plan.root.children == ()
        assert plan.planning_time_ms == 0.123
        assert plan.execution_time_ms == 0.567

    def test_relation_name_optional_for_non_scan_nodes(self) -> None:
        payload = [
            {
                "Plan": {
                    "Node Type": "Aggregate",
                    "Total Cost": 10.0,
                    "Plan Rows": 1,
                }
            }
        ]

        plan = parse_explain_json(payload)

        assert plan.root.relation_name is None


class TestNestedPlan:
    def test_parses_a_join_with_two_children(self) -> None:
        payload = [
            {
                "Plan": {
                    "Node Type": "Hash Join",
                    "Total Cost": 500.0,
                    "Plan Rows": 1000,
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "orders",
                            "Total Cost": 100.0,
                            "Plan Rows": 1000,
                        },
                        {
                            "Node Type": "Index Scan",
                            "Relation Name": "users",
                            "Total Cost": 10.0,
                            "Plan Rows": 1,
                        },
                    ],
                }
            }
        ]

        plan = parse_explain_json(payload)

        assert plan.root.node_type == "Hash Join"
        assert len(plan.root.children) == 2
        assert plan.root.children[0].relation_name == "orders"
        assert plan.root.children[1].relation_name == "users"

    def test_deeply_nested_plan_parses_without_error(self) -> None:
        node: dict = {"Node Type": "Seq Scan", "Total Cost": 1.0, "Plan Rows": 1}
        for _ in range(100):
            node = {
                "Node Type": "Nested Loop",
                "Total Cost": 1.0,
                "Plan Rows": 1,
                "Plans": [node],
            }
        payload = [{"Plan": node}]

        plan = parse_explain_json(payload)

        depth = 0
        current = plan.root
        while current.children:
            depth += 1
            current = current.children[0]
        assert depth == 100


class TestMalformedPayload:
    def test_empty_payload_raises_parsing_error(self) -> None:
        with pytest.raises(ParsingError):
            parse_explain_json([])

    def test_missing_plan_key_raises_parsing_error(self) -> None:
        with pytest.raises(ParsingError):
            parse_explain_json([{"Planning Time": 0.5}])

    def test_node_missing_required_field_raises_parsing_error(self) -> None:
        payload = [{"Plan": {"Node Type": "Seq Scan"}}]  # missing Total Cost, Plan Rows

        with pytest.raises(ParsingError):
            parse_explain_json(payload)


class TestDeeplyNestedPlans:
    @staticmethod
    def _nested_payload(depth: int) -> list[dict]:
        node: dict = {
            "Node Type": "Seq Scan",
            "Relation Name": "t",
            "Total Cost": 1.0,
            "Plan Rows": 1,
        }
        for _ in range(depth):
            node = {
                "Node Type": "Nested Loop",
                "Total Cost": 2.0,
                "Plan Rows": 2,
                "Plans": [node],
            }
        return [{"Plan": node, "Planning Time": 0.1, "Execution Time": 1.0}]

    def test_handles_realistically_deep_plans(self) -> None:
        # Far deeper than any plan PostgreSQL produces in practice.
        plan = parse_explain_json(self._nested_payload(200))
        assert plan.root.node_type == "Nested Loop"

    def test_pathological_depth_raises_parsing_error_not_recursion_error(self) -> None:
        # NFR-X.3: no raw stdlib exception may cross this boundary.
        with pytest.raises(ParsingError):
            parse_explain_json(self._nested_payload(5000))

class TestSortFieldExtraction:
    def test_populates_sort_fields_when_present(self) -> None:
        payload = [{
            "Plan": {
                "Node Type": "Sort",
                "Total Cost": 100.0,
                "Plan Rows": 1000,
                "Actual Rows": 1000,
                "Sort Key": ["created_at DESC", "id"],
                "Sort Method": "external merge",
                "Sort Space Type": "Disk",
                "Sort Space Used": 45_000,
            }
        }]

        plan = parse_explain_json(payload)

        assert plan.root.sort_key == ("created_at DESC", "id")
        assert plan.root.sort_method == "external merge"
        assert plan.root.sort_space_type == "Disk"
        assert plan.root.sort_space_used_kb == 45_000

    def test_sort_fields_default_when_absent(self) -> None:
        # A non-sort node (or a plan-only EXPLAIN) carries none of them.
        payload = [{
            "Plan": {
                "Node Type": "Seq Scan",
                "Relation Name": "users",
                "Total Cost": 10.0,
                "Plan Rows": 5,
            }
        }]

        plan = parse_explain_json(payload)

        assert plan.root.sort_key == ()
        assert plan.root.sort_method is None
        assert plan.root.sort_space_type is None
        assert plan.root.sort_space_used_kb is None