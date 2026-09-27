"""Recommendation engine.

Unifies the three finding sources -- plan `Finding`s (Sprint 6),
`IndexRecommendation`s (Sprint 7), and `AntiPatternFinding`s (Sprint 8)
-- into one deduplicated, ranked list of `Recommendation` objects
(FR-3.7.1, FR-3.7.4). This closes Phase 3.

Aggregation avoids double-reporting one problem (FR-3.7.1). The index
advisor is driven solely by SEQ_SCAN_LARGE_TABLE findings, so an index
recommendation *is the fix for* a seq-scan finding on the same table.
The engine therefore emits the index recommendation and folds the
corresponding seq-scan finding into it, rather than reporting both. A
seq-scan finding with no index recommendation (an unfiltered scan, or
columns that couldn't be attributed) still yields a standalone
recommendation with general advice. Index recs are the only source that
overlaps another, so this is the only merge required.

Ranking (US9.4) uses an impact proxy until precise estimates arrive in
Phase 4: impact tier, then occurrence count, then confidence, then a
stable insertion tiebreak -- deterministic for identical input
(NFR-4.3). Impact tier is separate from confidence, honoring the
severity-vs-confidence distinction: a SELECT * is HIGH confidence but
LOW impact, so it never outranks a genuinely costly issue.

The engine depends only on data models and the builders -- it has no
knowledge of the CLI or report formatting (NFR-3.7.1).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

from sqlcoach.advisor.anti_patterns.base import AntiPatternFinding
from sqlcoach.advisor.recommendation_builders import (
    from_anti_pattern,
    from_index_recommendation,
    from_plan_finding,
)
from sqlcoach.analyzer.base import Finding, Severity
from sqlcoach.models.index_recommendation import IndexRecommendation
from sqlcoach.models.recommendation import ConfidenceLevel, Recommendation

_SEQ_SCAN_CODE = "SEQ_SCAN_LARGE_TABLE"

_SEVERITY_TIER = {Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1}
_CONFIDENCE_TIER = {
    ConfidenceLevel.HIGH: 3,
    ConfidenceLevel.MEDIUM: 2,
    ConfidenceLevel.LOW: 1,
}

# Index recommendations address missing indexes on large tables -- the
# highest-value class of fix -- so they enter at the top impact tier.
# Confidence (a separate axis) still captures how sure we are.
_INDEX_IMPACT_TIER = 3


class _Ranked(NamedTuple):
    impact: int
    occurrences: int
    confidence: int
    order: int
    recommendation: Recommendation


def _with_occurrences(recommendation: Recommendation, count: int) -> Recommendation:
    """Append an occurrence note to the problem when a finding recurred,
    surfacing frequency without changing the Recommendation model.
    """
    if count <= 1:
        return recommendation
    return recommendation.model_copy(
        update={"problem": f"{recommendation.problem} (detected in {count} queries)"}
    )


def _group_by_code_and_relation(findings):  # type: ignore[no-untyped-def]
    """Group findings by (code, relation_name), preserving first-seen order."""
    groups: dict[tuple[str, object], list] = {}
    for finding in findings:
        groups.setdefault((finding.code, finding.relation_name), []).append(finding)
    return groups


class RecommendationEngine:
    """Aggregates and ranks recommendations from all finding sources."""

    def generate(
        self,
        *,
        plan_findings: Sequence[Finding] = (),
        index_recommendations: Sequence[IndexRecommendation] = (),
        anti_pattern_findings: Sequence[AntiPatternFinding] = (),
    ) -> list[Recommendation]:
        """Produce one ranked, deduplicated recommendation list."""
        ranked: list[_Ranked] = []
        order = 0

        # 1. Index recommendations (already deduped by the advisor). These
        #    also tell us which tables' seq-scan findings to fold in.
        indexed_tables: set[str] = set()
        for index_rec in index_recommendations:
            indexed_tables.add(index_rec.table)
            recommendation = from_index_recommendation(index_rec)
            ranked.append(
                _Ranked(
                    impact=_INDEX_IMPACT_TIER,
                    occurrences=1,
                    confidence=_CONFIDENCE_TIER[recommendation.confidence],
                    order=order,
                    recommendation=recommendation,
                )
            )
            order += 1

        # 2. Plan findings, deduped by (code, relation). Seq-scan findings
        #    on a table that already has an index recommendation are folded
        #    into it and not reported again.
        for (code, relation), group in _group_by_code_and_relation(plan_findings).items():
            if code == _SEQ_SCAN_CODE and relation in indexed_tables:
                continue
            representative = group[0]
            recommendation = _with_occurrences(
                from_plan_finding(representative), len(group)
            )
            ranked.append(
                _Ranked(
                    impact=_SEVERITY_TIER[representative.severity],
                    occurrences=len(group),
                    confidence=_CONFIDENCE_TIER[recommendation.confidence],
                    order=order,
                    recommendation=recommendation,
                )
            )
            order += 1

        # 3. Anti-patterns, deduped by (code, relation).
        for (code, relation), group in _group_by_code_and_relation(
            anti_pattern_findings
        ).items():
            representative = group[0]
            recommendation = _with_occurrences(
                from_anti_pattern(representative), len(group)
            )
            ranked.append(
                _Ranked(
                    impact=_SEVERITY_TIER[representative.severity],
                    occurrences=len(group),
                    confidence=_CONFIDENCE_TIER[recommendation.confidence],
                    order=order,
                    recommendation=recommendation,
                )
            )
            order += 1

        ranked.sort(key=lambda r: (-r.impact, -r.occurrences, -r.confidence, r.order))
        return [r.recommendation for r in ranked]