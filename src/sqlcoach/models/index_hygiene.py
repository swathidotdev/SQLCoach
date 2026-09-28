"""Index-hygiene finding model.

The output of the duplicate- and unused-index detectors (Sprint 11).
A distinct finding type because these recommend *dropping* an index --
a destructive action -- rather than adding one or rewriting a query.
Carries both severity (for ranking) and confidence (for the eventual
recommendation), reusing the shared Severity / ConfidenceLevel scales.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from sqlcoach.analyzer.base import MetricValue, Severity
from sqlcoach.models.recommendation import ConfidenceLevel


class IndexHygieneFinding(BaseModel):
    """A recommendation to drop a redundant or unused index.

    Attributes:
        code: "DUPLICATE_INDEX" or "UNUSED_INDEX".
        detector: Name of the detector that produced it.
        severity: Impact tier (index hygiene is a write/storage cost, not
            a read-latency emergency -- typically MEDIUM).
        confidence: How sure we are. Duplicate redundancy is provable
            (HIGH); "unused" is a snapshot signal, not proof (MEDIUM).
        summary: Human-readable description, including the verify caveat.
        table: The table the index belongs to.
        index_name: The index proposed for dropping.
        drop_statement: The generated DROP INDEX statement. Never executed
            by SQLCoach (NFR-3.5.1).
        metrics: Supporting numbers (e.g. scan_count).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    detector: str
    severity: Severity
    confidence: ConfidenceLevel
    summary: str
    table: str
    index_name: str
    drop_statement: str
    metrics: dict[str, MetricValue] = Field(default_factory=dict)