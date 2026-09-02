"""Analyzer core contracts.

Defines the data and interfaces shared by every execution-plan
detector: the `Finding` a detector emits, the `Severity` scale, the
`AnalysisContext` that carries tuned thresholds, and the
`PlanDetector` protocol each detector implements.

`Finding` is deliberately thinner than `Recommendation` (Sprint 2's
model). A detector's job ends at "here is an issue, at this node, with
these supporting numbers"; turning that into a Problem/Root Cause/
Solution/Impact/Confidence narrative is the recommendation engine's
job (Sprint 9, NFR-3.4). Keeping the analyzer's output decoupled from
that richer shape is what lets the analyzer, index advisor, and
recommendation engine evolve independently.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Protocol, Union, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from sqlcoach.config import (
    DEFAULT_CARDINALITY_MIN_ROWS,
    DEFAULT_CARDINALITY_MISESTIMATION_RATIO,
    DEFAULT_NESTED_LOOP_ROW_THRESHOLD,
    DEFAULT_SEQ_SCAN_ROW_THRESHOLD,
    Settings,
)
from sqlcoach.models.execution_plan import PlanNode

#: Supporting numeric evidence attached to a Finding (row counts,
#: thresholds, ratios). Kept numeric so downstream aggregation and
#: ranking (Sprint 9) can consume it without re-parsing strings.
MetricValue = Union[int, float]


class Severity(str, Enum):
    """How serious a detected issue is, on a coarse three-point scale.

    Distinct from the recommendation engine's Confidence Level (Sprint
    9): severity is "how bad is this if real", confidence is "how sure
    are we it's real". A detector sets severity; the recommendation
    engine sets confidence.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Finding(BaseModel):
    """One performance issue detected at one plan node.

    Attributes:
        code: Stable machine-readable identifier for the kind of issue
            (e.g. "SEQ_SCAN_LARGE_TABLE"). Sprint 9 maps this to a
            recommendation template, so it must not change casually.
        detector: Name of the detector that produced this finding
            (e.g. "sequential_scan"). Useful for filtering and for
            attributing output.
        severity: How serious the issue is if genuine.
        summary: A short, human-readable one-line description. Not the
            full explanation -- that's the recommendation engine's job.
        node_type: The plan node type the issue was found on (e.g.
            "Seq Scan"), denormalized from the node so downstream
            consumers needn't hold a PlanNode reference.
        relation_name: The table/index involved, when the node has one.
            This is the key link the index advisor (Sprint 7) uses to
            tie a finding back to a table it can recommend an index on.
        metrics: Supporting numbers behind the finding (e.g. rows
            scanned, the threshold crossed). Purely numeric.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    detector: str
    severity: Severity
    summary: str
    node_type: str
    relation_name: Optional[str] = None
    metrics: dict[str, MetricValue] = Field(default_factory=dict)


class AnalysisContext(BaseModel):
    """Tuned thresholds passed to every detector during a run.

    This is the seam between user configuration (`Settings`) and the
    detectors. Detectors depend only on this small, purpose-built
    value object rather than on the full `Settings` (which also carries
    logging config they have no business seeing) -- Interface
    Segregation. It also lets tests construct a context with exactly
    the thresholds under test, without building a whole Settings.

    The fields carry defaults purely as a test convenience, so a test
    exercising one detector need not specify thresholds for the others.
    In production the context is always built via `from_settings`, which
    supplies every value explicitly from validated Settings -- so these
    defaults are never the operative values at runtime, and the shared
    constants keep them from drifting out of step with Settings.

    Attributes:
        seq_scan_row_threshold: A sequential scan returning at least
            this many rows is flagged as a candidate for indexing
            (FR-3.4.1). Row count is taken from actual rows when the
            plan was produced with ANALYZE, otherwise the planner's
            estimate.
        nested_loop_row_threshold: A nested-loop join whose outer side
            drives at least this many inner-side iterations is flagged
            as a likely bottleneck (FR-3.4.2).
        cardinality_misestimation_ratio: The estimated/actual row-count
            divergence factor (either direction) at or above which a
            node is flagged as a cardinality misestimation (FR-3.4.4).
        cardinality_min_rows: Floor on the larger of estimated/actual
            rows below which a cardinality misestimation is ignored, to
            suppress tiny-count noise.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    seq_scan_row_threshold: int = Field(default=DEFAULT_SEQ_SCAN_ROW_THRESHOLD, ge=1)
    nested_loop_row_threshold: int = Field(
        default=DEFAULT_NESTED_LOOP_ROW_THRESHOLD, ge=1
    )
    cardinality_misestimation_ratio: float = Field(
        default=DEFAULT_CARDINALITY_MISESTIMATION_RATIO, gt=1.0
    )
    cardinality_min_rows: int = Field(default=DEFAULT_CARDINALITY_MIN_ROWS, ge=0)

    @classmethod
    def from_settings(cls, settings: Settings) -> "AnalysisContext":
        """Build an AnalysisContext from validated Settings."""
        return cls(
            seq_scan_row_threshold=settings.seq_scan_row_threshold,
            nested_loop_row_threshold=settings.nested_loop_row_threshold,
            cardinality_misestimation_ratio=settings.cardinality_misestimation_ratio,
            cardinality_min_rows=settings.cardinality_min_rows,
        )


@runtime_checkable
class PlanDetector(Protocol):
    """Structural interface for a single execution-plan detector.

    Each detector inspects one plan node at a time and returns any
    findings for that node. The `PlanAnalyzer` handles tree traversal;
    a detector never walks children itself -- it will be called once
    per node in the tree. A detector that doesn't apply to a given node
    returns an empty list.

    Implemented as a Protocol (structural typing) rather than an ABC,
    matching the parser layer's `Parser` protocol: a detector is any
    object with a `name` and a conforming `detect` method, with no
    inheritance required (composition over inheritance).
    """

    name: str

    def detect(self, node: PlanNode, context: AnalysisContext) -> list[Finding]:
        """Return findings for `node`, or an empty list if none apply."""
        ...