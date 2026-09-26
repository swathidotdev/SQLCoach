"""Index recommendation domain model.

The index advisor's output (Sprint 7). Deliberately narrower than the
unified `Recommendation` model (Sprint 2): it captures the structured
facts of a proposed index -- table, ordered key columns, any covering
INCLUDE columns, the ready-to-run CREATE INDEX, and why it's suggested
-- while the Recommendation *engine* (Sprint 9) is what turns this,
alongside anti-pattern and plan findings, into the full
Problem/Root-Cause/.../Risks narrative. Keeping the advisor's output
focused here is what lets the advisor and the recommendation engine
evolve independently.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from sqlcoach.models.recommendation import ConfidenceLevel


class IndexKind(str, Enum):
    """The shape of a recommended index."""

    SINGLE_COLUMN = "single_column"
    COMPOSITE = "composite"
    COVERING = "covering"


class IndexRecommendation(BaseModel):
    """A proposed index for one table, with ready-to-run SQL.

    Attributes:
        table: The table the index would be created on.
        columns: The index key columns, in order. Order is significant
            for composite indexes (a b-tree index can only use a
            leading prefix of its key columns).
        included_columns: Non-key columns carried in the index via
            INCLUDE, enabling index-only scans (covering indexes).
            Empty for non-covering indexes.
        kind: Whether this is a single-column, composite, or covering
            index.
        create_statement: The ready-to-run CREATE INDEX statement
            (US7.4). SQLCoach never executes this itself (NFR-3.5.1);
            it is only ever generated for the user to run.
        rationale: A short explanation of why this index is suggested.
            The fuller Problem/Root-Cause/.../Risks narrative is built
            later by the recommendation engine (Sprint 9).
        confidence: How likely this index is to help, reusing the
            shared ConfidenceLevel scale.
        source_finding_code: The code of the analyzer finding that
            motivated this recommendation (e.g. "SEQ_SCAN_LARGE_TABLE"),
            for traceability back to the evidence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    table: str
    columns: tuple[str, ...] = Field(min_length=1)
    included_columns: tuple[str, ...] = Field(default_factory=tuple)
    kind: IndexKind
    create_statement: str
    rationale: str
    confidence: ConfidenceLevel
    source_finding_code: str