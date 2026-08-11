"""Recommendation domain model.

Every performance recommendation SQLCoach surfaces must fully explain
itself: this model captures the full narrative arc mandated by project
instructions and NFR-X.5, not just a bare suggestion (FR-2.3).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ConfidenceLevel(str, Enum):
    """How certain SQLCoach is that a recommendation will help."""

    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class Recommendation(BaseModel):
    """A single, fully-explained optimization recommendation.

    Attributes:
        problem: What is wrong, in plain terms.
        root_cause: Why the problem occurs.
        technical_explanation: The PostgreSQL-level mechanics behind
            the problem (e.g. why a sequential scan happens, why a
            hash join spills to disk).
        recommended_solution: What should change.
        sql_example: A concrete, ready-to-run SQL statement
            implementing the solution, when applicable (e.g. a
            CREATE INDEX statement). None for recommendations that
            aren't expressible as SQL (e.g. "avoid SELECT *").
        expected_impact: A human-readable description of the expected
            improvement. Kept as free text here since precise
            estimation methodology arrives in Phase 4 (FR-4.5); this
            field just holds whatever the producing detector can
            currently say.
        confidence: Qualitative confidence rating for this recommendation.
        risks: Trade-offs or risks of applying this recommendation
            (e.g. "adds write overhead", "increases index storage").
            Empty tuple when there are none worth calling out.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    problem: str
    root_cause: str
    technical_explanation: str
    recommended_solution: str
    sql_example: Optional[str] = None
    expected_impact: str
    confidence: ConfidenceLevel
    risks: tuple[str, ...] = Field(default_factory=tuple)