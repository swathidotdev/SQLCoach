"""ExecutionPlan domain model.

Represents a parsed PostgreSQL `EXPLAIN ANALYZE` plan as a tree of
`PlanNode` objects, plus query-level timing metadata (FR-2.2). This
model is deliberately shaped to survive arbitrarily deep, multi-way
join trees without recursion errors (NFR-3.1) -- Pydantic validates
recursive models natively.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PlanNode(BaseModel):
    """A single node in a PostgreSQL EXPLAIN plan tree.

    Attributes:
        node_type: Postgres plan node type, e.g. "Seq Scan",
            "Index Scan", "Hash Join", "Sort".
        relation_name: Table or index name this node operates on, if
            applicable (e.g. present on scan nodes, absent on joins).
        estimated_cost: Planner's estimated total cost for this node.
        estimated_rows: Planner's estimated row count for this node.
        actual_rows: Actual row count observed during ANALYZE, if the
            plan was produced with ANALYZE. None for plan-only EXPLAIN.
        actual_time_ms: Actual total time in milliseconds spent in
            this node (inclusive of children), if ANALYZE was used.
        children: Child plan nodes (e.g. the two sides of a join).
            Empty for leaf nodes such as a bare Seq Scan.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_type: str
    relation_name: Optional[str] = None
    estimated_cost: float = Field(ge=0)
    estimated_rows: int = Field(ge=0)
    actual_rows: Optional[int] = Field(default=None, ge=0)
    actual_time_ms: Optional[float] = Field(default=None, ge=0)
    children: tuple["PlanNode", ...] = Field(default_factory=tuple)


# Required for self-referencing frozen models: resolves the forward
# reference to "PlanNode" inside its own field definition.
PlanNode.model_rebuild()


class ExecutionPlan(BaseModel):
    """A full EXPLAIN ANALYZE result for a single query.

    Attributes:
        root: The top-level plan node (the root of the plan tree).
        planning_time_ms: Time Postgres spent planning the query, if
            reported (present when EXPLAIN ANALYZE is used).
        execution_time_ms: Total time Postgres spent executing the
            query, if reported.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    root: PlanNode
    planning_time_ms: Optional[float] = Field(default=None, ge=0)
    execution_time_ms: Optional[float] = Field(default=None, ge=0)