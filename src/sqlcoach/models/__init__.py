"""Domain models.

Pydantic data contracts shared across every other layer: `Query`,
`ExecutionPlan`, `Recommendation`, and `Report`. Per NFR-2.4, this
package has no dependency on the CLI or database layers — dependencies
only ever point inward, toward these models. Introduced in Sprint 2
(US2.1).
"""

from __future__ import annotations

from sqlcoach.models.execution_plan import ExecutionPlan, PlanNode
from sqlcoach.models.query import Query, QuerySource
from sqlcoach.models.recommendation import ConfidenceLevel, Recommendation
from sqlcoach.models.report import Report

__all__ = [
    "ConfidenceLevel",
    "ExecutionPlan",
    "PlanNode",
    "Query",
    "QuerySource",
    "Recommendation",
    "Report",
]