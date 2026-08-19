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