"""EXPLAIN JSON parser.

Converts the raw JSON payload returned by
`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` into the `ExecutionPlan`/
`PlanNode` domain models from Sprint 2 (FR-3.2.3, FR-2.2).
"""

from __future__ import annotations

from typing import Any

from sqlcoach.exceptions import ParsingError
from sqlcoach.models.execution_plan import ExecutionPlan, PlanNode


def _parse_node(raw_node: dict[str, Any]) -> PlanNode:
    """Recursively convert one raw EXPLAIN plan node dict into a PlanNode."""
    children_raw = raw_node.get("Plans", [])
    children = tuple(_parse_node(child) for child in children_raw)

    try:
        return PlanNode(
            node_type=raw_node["Node Type"],
            relation_name=raw_node.get("Relation Name"),
            estimated_cost=raw_node["Total Cost"],
            estimated_rows=raw_node["Plan Rows"],
            actual_rows=raw_node.get("Actual Rows"),
            actual_time_ms=raw_node.get("Actual Total Time"),
            children=children,
        )
    except KeyError as exc:
        raise ParsingError(
            "EXPLAIN plan node is missing a required field",
            details={"missing_key": str(exc), "node_type": raw_node.get("Node Type")},
        ) from exc


def parse_explain_json(raw_payload: list[dict[str, Any]]) -> ExecutionPlan:
    """Parse the JSON payload from EXPLAIN (..., FORMAT JSON) into an ExecutionPlan.

    Args:
        raw_payload: The parsed JSON value returned by Postgres for
            `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) <statement>` -- a
            list containing exactly one plan object.

    Returns:
        The corresponding ExecutionPlan.

    Raises:
        ParsingError: If the payload doesn't have the expected shape
            (empty list, missing "Plan" key, or a plan node missing a
            required field).
    """
    if not raw_payload:
        raise ParsingError("EXPLAIN returned an empty result")

    top_level = raw_payload[0]

    if "Plan" not in top_level:
        raise ParsingError(
            "EXPLAIN JSON payload is missing the top-level 'Plan' key",
            details={"payload_keys": list(top_level.keys())},
        )

    root = _parse_node(top_level["Plan"])

    return ExecutionPlan(
        root=root,
        planning_time_ms=top_level.get("Planning Time"),
        execution_time_ms=top_level.get("Execution Time"),
    )