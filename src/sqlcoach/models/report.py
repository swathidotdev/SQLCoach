"""Report domain model.

Aggregates every Query analyzed in a single run alongside the
Recommendations produced for it, giving CLI/report-formatting code one
object to render rather than three disconnected collections (FR-2.4).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from sqlcoach.models.query import Query
from sqlcoach.models.recommendation import Recommendation


class Report(BaseModel):
    """The result of a single SQLCoach analysis run.

    Attributes:
        generated_at: UTC timestamp when this report was produced.
        queries_analyzed: Every Query that was part of this run.
        recommendations: Every Recommendation produced across all
            analyzed queries, typically already ranked by impact
            (ranking itself is introduced in Sprint 9).
        source_description: Human-readable description of what was
            analyzed (e.g. a file path, or "live database: mydb").
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    queries_analyzed: tuple[Query, ...] = Field(default_factory=tuple)
    recommendations: tuple[Recommendation, ...] = Field(default_factory=tuple)
    source_description: Optional[str] = None