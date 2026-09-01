"""Execution plan domain models.

Represents a parsed PostgreSQL EXPLAIN plan as a tree of `PlanNode`
objects under an `ExecutionPlan` wrapper (FR-2.2). The tree mirrors
the "Plans" nesting in EXPLAIN's JSON output.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PlanNode(BaseModel):
    """A single node in a PostgreSQL execution plan tree.

    Attributes:
        node_type: The plan node type as PostgreSQL names it (e.g.
            "Seq Scan", "Index Scan", "Nested Loop", "Hash Join",
            "Sort").
        relation_name: The table or index the node operates on, when
            applicable (scans). None for nodes with no single relation
            (joins, sorts, aggregates).
        estimated_cost: The planner's total cost estimate for the node.
        estimated_rows: The planner's estimated output row count.
        actual_rows: The measured output row count, present only when
            the plan was produced with ANALYZE. None otherwise.
        actual_time_ms: The measured total time for the node in
            milliseconds, present only with ANALYZE. None otherwise.
        children: Child plan nodes (e.g. the two sides of a join).
            Empty for leaf nodes such as a bare Seq Scan.
        sort_key: For sort nodes, the ordering expressions as PostgreSQL
            formats them (e.g. "created_at DESC", "id"). Empty for
            non-sort nodes. Preserved verbatim; consumed today by the
            expensive-sort detector's message and positioned for the
            index advisor (Sprint 7), which can recommend an index that
            provides pre-sorted output.
        sort_method: For sort nodes produced with ANALYZE, the method
            PostgreSQL used at runtime (e.g. "quicksort", "top-N
            heapsort", "external merge"). None for non-sort nodes and
            for plan-only EXPLAIN, where the runtime method is unknown.
        sort_space_type: For sort nodes produced with ANALYZE, where the
            sort's working set lived: "Memory" or "Disk". "Disk"
            indicates the sort exceeded work_mem and spilled. None when
            not applicable.
        sort_space_used_kb: For sort nodes produced with ANALYZE, the
            peak sort space used, in kilobytes. None when not applicable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_type: str
    relation_name: Optional[str] = None
    estimated_cost: float = Field(ge=0)
    estimated_rows: int = Field(ge=0)
    actual_rows: Optional[int] = Field(default=None, ge=0)
    actual_time_ms: Optional[float] = Field(default=None, ge=0)
    children: tuple["PlanNode", ...] = Field(default_factory=tuple)
    sort_key: tuple[str, ...] = Field(default_factory=tuple)
    sort_method: Optional[str] = None
    sort_space_type: Optional[str] = None
    sort_space_used_kb: Optional[int] = Field(default=None, ge=0)


class ExecutionPlan(BaseModel):
    """A parsed EXPLAIN plan: a root node plus run-level timings.

    Attributes:
        root: The root plan node; all other nodes hang beneath it.
        planning_time_ms: Planning time in milliseconds, when reported.
        execution_time_ms: Total execution time in milliseconds, present
            only when the plan was produced with ANALYZE.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    root: PlanNode
    planning_time_ms: Optional[float] = Field(default=None, ge=0)
    execution_time_ms: Optional[float] = Field(default=None, ge=0)