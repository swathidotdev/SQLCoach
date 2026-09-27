"""Confidence heuristics for recommendations (US9.3, FR-3.7.3).

Confidence answers "how sure are we this recommendation will help",
which is deliberately separate from severity ("how bad is the issue if
real"). The rules here are documented and centralized rather than
scattered as inline literals, so scoring is defensible and testable.
"""

from __future__ import annotations

from sqlcoach.analyzer.base import Severity
from sqlcoach.models.recommendation import ConfidenceLevel

_SEVERITY_TO_CONFIDENCE = {
    Severity.HIGH: ConfidenceLevel.HIGH,
    Severity.MEDIUM: ConfidenceLevel.MEDIUM,
    Severity.LOW: ConfidenceLevel.LOW,
}

# Anti-patterns are detected statically from syntax, so the *diagnosis* is
# usually certain even when impact is modest -- hence HIGH confidence. The
# exception is N+1: the repeated-query shape is clear, but whether it's an
# actual bug or an intentional pattern can't be known from SQL alone, so it
# is the softer MEDIUM.
_ANTI_PATTERN_CONFIDENCE = {
    "SELECT_STAR": ConfidenceLevel.HIGH,
    "LEADING_WILDCARD_LIKE": ConfidenceLevel.HIGH,
    "ORDER_BY_RANDOM": ConfidenceLevel.HIGH,
    "N_PLUS_ONE": ConfidenceLevel.MEDIUM,
}


def confidence_from_severity(severity: Severity) -> ConfidenceLevel:
    """Confidence for evidence-based findings (plan analysis, index recs).

    These rest on observed execution behavior, so how sure we are tracks
    how strong that evidence is -- which the detector already encoded in
    severity: an issue confirmed by ANALYZE actuals is HIGH severity and
    HIGH confidence; one resting on a planner estimate is the softer
    MEDIUM. The mapping is therefore direct.
    """
    return _SEVERITY_TO_CONFIDENCE[severity]


def confidence_for_anti_pattern(code: str) -> ConfidenceLevel:
    """Confidence for a static anti-pattern, by its code.

    Static syntax detection means the finding is almost always genuinely
    present, so most anti-patterns are HIGH confidence; N+1 is MEDIUM
    because its intent can't be judged from SQL alone. Unknown codes
    default to MEDIUM rather than overclaiming.
    """
    return _ANTI_PATTERN_CONFIDENCE.get(code, ConfidenceLevel.MEDIUM)