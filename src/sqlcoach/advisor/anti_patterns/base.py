"""Anti-pattern detection core contracts.

Defines the data and interface shared by every anti-pattern detector:
the `AntiPatternFinding` a detector emits, the `ParsedQuery` it inspects,
and the `AntiPatternDetector` protocol it implements.

Unlike a plan `Finding` (Sprint 6), which is anchored to an execution-
plan node, an anti-pattern is anchored to a *query* and detected
statically -- so it has no node type. `AntiPatternFinding` is its own
cohesive model rather than a reuse of the plan finding, while sharing
the `Severity` and `MetricValue` vocabulary so the recommendation engine
(Sprint 9) can treat all finding kinds uniformly.
"""

from __future__ import annotations

from typing import NamedTuple, Optional, Protocol, Sequence, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field
from sqlglot import exp

from sqlcoach.analyzer.base import MetricValue, Severity
from sqlcoach.models.query import Query


class AntiPatternFinding(BaseModel):
    """One anti-pattern detected in one query.

    Attributes:
        code: Stable machine-readable identifier for the anti-pattern
            (e.g. "SELECT_STAR"). Sprint 9 maps this to a recommendation
            template, so it must not change casually.
        detector: Name of the detector that produced this finding.
        severity: How serious the anti-pattern is.
        summary: A short, human-readable one-line description.
        source_location: Where the offending query came from (e.g. a
            file path and line number), when known.
        relation_name: The table involved, when the anti-pattern is
            tied to one.
        metrics: Supporting numbers (e.g. an N+1 occurrence count).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    detector: str
    severity: Severity
    summary: str
    source_location: Optional[str] = None
    relation_name: Optional[str] = None
    metrics: dict[str, MetricValue] = Field(default_factory=dict)


class ParsedQuery(NamedTuple):
    """A query paired with its parsed AST.

    The `AntiPatternAnalyzer` parses each query exactly once and hands
    this pair to every detector, so no detector re-parses. `statement`
    is None when the query could not be parsed; per-query detectors skip
    those, while workload-level detectors (N+1) can still fall back to
    the query's own fingerprint.
    """

    query: Query
    statement: Optional[exp.Expression]


@runtime_checkable
class AntiPatternDetector(Protocol):
    """Structural interface for a single anti-pattern detector.

    Every detector receives the whole workload of `ParsedQuery` objects,
    not one query -- this lets per-query detectors (SELECT *, LIKE,
    ORDER BY RANDOM) loop internally while workload-level detectors (N+1)
    cluster across queries, all behind one registry. Implemented as a
    Protocol (structural typing), matching the plan detector and parser
    layers: any object with a `name` and a conforming `detect` method
    qualifies, no inheritance required.
    """

    name: str

    def detect(
        self, parsed_queries: Sequence[ParsedQuery]
    ) -> list[AntiPatternFinding]:
        """Return findings across the workload, or an empty list."""
        ...