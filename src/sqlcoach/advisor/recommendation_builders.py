"""Recommendation builders.

Convert each of the three finding sources -- plan `Finding`s (Sprint 6),
`IndexRecommendation`s (Sprint 7), and `AntiPatternFinding`s (Sprint 8)
-- into the unified 8-field `Recommendation` model (FR-3.7.2). Each
builder fills Problem / Root Cause / Technical Explanation / Recommended
Solution / SQL Example / Expected Impact / Confidence / Risks from a
per-code template, so the narrative content lives in one documented
place rather than being scattered.

Expected impact is qualitative here (NFR-4.2): precise before/after
estimates arrive with the impact estimator in Phase 4 (FR-4.5).
"""

from __future__ import annotations

import logging
from typing import NamedTuple

from sqlcoach.advisor.anti_patterns.base import AntiPatternFinding
from sqlcoach.advisor.confidence import (
    confidence_for_anti_pattern,
    confidence_from_severity,
)
from sqlcoach.analyzer.base import Finding
from sqlcoach.models.index_recommendation import IndexKind, IndexRecommendation
from sqlcoach.models.recommendation import ConfidenceLevel, Recommendation

logger = logging.getLogger(__name__)

_INDEX_WRITE_RISK = (
    "Every index adds write overhead on INSERT/UPDATE/DELETE and consumes storage; "
    "add it only if this access pattern is frequent."
)


class _Template(NamedTuple):
    """The static narrative for one finding code. ``{relation}`` in any
    field is filled with the finding's table (or a neutral fallback).
    """

    root_cause: str
    technical_explanation: str
    recommended_solution: str
    expected_impact: str
    risks: tuple[str, ...]


def _fill(text: str, relation: str) -> str:
    return text.replace("{relation}", relation)


# ---- Plan findings -------------------------------------------------------

_PLAN_TEMPLATES: dict[str, _Template] = {
    "SEQ_SCAN_LARGE_TABLE": _Template(
        root_cause="No index exists that PostgreSQL can use for this query's filter "
        "on {relation}, so it reads the whole table.",
        technical_explanation="A sequential scan reads every row of {relation} and "
        "applies the filter afterward. A matching index would let PostgreSQL seek "
        "straight to the qualifying rows instead.",
        recommended_solution="Add an index on the column(s) this query filters or "
        "joins on for {relation}.",
        expected_impact="Replaces a full-table scan with a targeted index lookup; the "
        "larger the table, the greater the saving.",
        risks=(_INDEX_WRITE_RISK,),
    ),
    "NESTED_LOOP_LARGE_ROWCOUNT": _Template(
        root_cause="PostgreSQL chose a nested-loop join whose inner side runs once per "
        "outer row, and the outer row count is large.",
        technical_explanation="A nested loop is optimal for tiny inputs but scales as "
        "outer x inner. At large row counts a hash or merge join, or an index on the "
        "inner join key, is usually far cheaper.",
        recommended_solution="Add an index on the inner side's join key, or help the "
        "planner choose a hash/merge join (e.g. by fixing row estimates); confirm by "
        "re-checking the plan.",
        expected_impact="Turns repeated inner-side work into near-linear cost via an "
        "indexed lookup or a hash/merge join.",
        risks=("An index on the join key adds write overhead.",),
    ),
    "SORT_SPILLED_TO_DISK": _Template(
        root_cause="The sort's working set exceeded work_mem, so PostgreSQL spilled to "
        "an on-disk merge sort.",
        technical_explanation="Sorts that fit in work_mem use an in-memory quicksort; "
        "when they don't, PostgreSQL writes runs to temporary files and merges them, "
        "incurring extra I/O.",
        recommended_solution="Raise work_mem for this workload, or add an index that "
        "supplies the required order so the sort can be skipped.",
        expected_impact="Eliminates temporary-file I/O; an index providing pre-sorted "
        "output can remove the sort node entirely.",
        risks=(
            "Raising work_mem increases memory use per sort/hash across concurrent "
            "queries.",
        ),
    ),
    "CARDINALITY_MISESTIMATION": _Template(
        root_cause="The planner's row estimate for {relation} is far from reality, "
        "usually because table statistics are stale or missing.",
        technical_explanation="PostgreSQL costs plans from pg_statistic; wrong estimates "
        "lead it to pick poor join orders, join types, and scan methods. This "
        "divergence signals the statistics no longer reflect the data.",
        recommended_solution="Run ANALYZE on {relation} (or raise its statistics target "
        "for skewed columns) so the planner works from accurate estimates.",
        expected_impact="Accurate estimates let the planner choose better plans; the fix "
        "(ANALYZE) is cheap and low-risk.",
        risks=(),
    ),
}


def from_plan_finding(finding: Finding) -> Recommendation:
    """Build a Recommendation from a plan-analysis finding.

    Used for findings without a dedicated index recommendation (the
    aggregation step folds a seq scan into its index rec when one
    exists). The Problem is the finding's own summary; the rest comes
    from the per-code template.
    """
    relation = finding.relation_name or "the table"
    template = _PLAN_TEMPLATES.get(finding.code)
    if template is None:
        logger.warning("No recommendation template for plan code %s", finding.code)
        return _generic(finding.summary, confidence_from_severity(finding.severity))
    return Recommendation(
        problem=finding.summary,
        root_cause=_fill(template.root_cause, relation),
        technical_explanation=_fill(template.technical_explanation, relation),
        recommended_solution=_fill(template.recommended_solution, relation),
        sql_example=None,
        expected_impact=_fill(template.expected_impact, relation),
        confidence=confidence_from_severity(finding.severity),
        risks=template.risks,
    )


# ---- Anti-patterns -------------------------------------------------------

_ANTI_PATTERN_TEMPLATES: dict[str, _Template] = {
    "SELECT_STAR": _Template(
        root_cause="The query requests every column with *, including ones it doesn't "
        "use.",
        technical_explanation="SELECT * transfers and materializes all columns, raising "
        "I/O, and prevents index-only scans since a covering index can't satisfy a "
        "query that needs every column.",
        recommended_solution="List only the columns the query actually needs.",
        expected_impact="Reduces row width transferred and can unlock index-only scans.",
        risks=(),
    ),
    "LEADING_WILDCARD_LIKE": _Template(
        root_cause="The LIKE pattern begins with a wildcard, so no b-tree index prefix "
        "can be used.",
        technical_explanation="A b-tree index seeks by known leading characters. A "
        "pattern like '%value' has no fixed prefix, so PostgreSQL must scan and test "
        "every row.",
        recommended_solution="If leading-wildcard search is required, use a trigram "
        "(pg_trgm) index or full-text search; otherwise anchor the pattern (e.g. "
        "'value%').",
        expected_impact="A trigram or full-text index can turn a full scan into an "
        "index-supported search.",
        risks=("Trigram and full-text indexes add write overhead and storage.",),
    ),
    "ORDER_BY_RANDOM": _Template(
        root_cause="ORDER BY RANDOM() assigns a random value to every row and sorts the "
        "entire result on each execution.",
        technical_explanation="There is no index for a per-execution random ordering, so "
        "PostgreSQL computes RANDOM() for all candidate rows and performs a full sort; "
        "cost grows with table size.",
        recommended_solution="For random sampling use TABLESAMPLE, or select random ids "
        "via a keyset/offset approach, instead of sorting the whole set.",
        expected_impact="Sampling avoids the full sort -- dramatically cheaper on large "
        "tables.",
        risks=(
            "TABLESAMPLE is approximate; choose the method that fits your sampling "
            "needs.",
        ),
    ),
    "N_PLUS_ONE": _Template(
        root_cause="The application issues one query per row in a loop instead of a "
        "single batched query.",
        technical_explanation="Each query carries fixed planning and round-trip "
        "overhead. Repeating it N times multiplies that overhead and defeats the "
        "database's set-based strengths.",
        recommended_solution="Batch the repeated lookups into one query using IN (...) "
        "or a JOIN, or use your ORM's eager-loading/batch facility.",
        expected_impact="Collapses N round trips into one; the improvement scales with "
        "N.",
        risks=(),
    ),
}


def from_anti_pattern(finding: AntiPatternFinding) -> Recommendation:
    """Build a Recommendation from a static anti-pattern finding."""
    relation = finding.relation_name or "the table"
    template = _ANTI_PATTERN_TEMPLATES.get(finding.code)
    confidence = confidence_for_anti_pattern(finding.code)
    if template is None:
        logger.warning(
            "No recommendation template for anti-pattern code %s", finding.code
        )
        return _generic(finding.summary, confidence)
    return Recommendation(
        problem=finding.summary,
        root_cause=_fill(template.root_cause, relation),
        technical_explanation=_fill(template.technical_explanation, relation),
        recommended_solution=_fill(template.recommended_solution, relation),
        sql_example=None,  # anti-pattern fixes aren't a single generic statement
        expected_impact=_fill(template.expected_impact, relation),
        confidence=confidence,
        risks=template.risks,
    )


# ---- Index recommendations ----------------------------------------------

def from_index_recommendation(rec: IndexRecommendation) -> Recommendation:
    """Build a Recommendation from an index recommendation.

    The index rec already carries confidence and the ready-to-run SQL,
    so this maps it into the narrative shape and adds covering-specific
    explanation and risk when applicable.
    """
    columns = ", ".join(rec.columns)
    covering = rec.kind is IndexKind.COVERING
    kind_label = {
        IndexKind.SINGLE_COLUMN: "single-column",
        IndexKind.COMPOSITE: "composite",
        IndexKind.COVERING: "covering",
    }[rec.kind]

    if covering:
        included = ", ".join(rec.included_columns)
        technical_explanation = (
            f"An index on {rec.table} ({columns}) lets PostgreSQL seek directly to "
            f"matching rows, and because ({included}) are carried in the index via "
            f"INCLUDE, the query is satisfied by an index-only scan that skips heap "
            f"fetches entirely."
        )
        expected_impact = (
            "Replaces a full-table scan with an index-only scan, avoiding both the "
            "scan and the table-heap lookups."
        )
        risks = (_INDEX_WRITE_RISK, "INCLUDE columns further increase the index's size.")
    else:
        technical_explanation = (
            f"An index on {rec.table} ({columns}) lets PostgreSQL seek directly to "
            f"matching rows instead of scanning the whole table. For composite indexes, "
            f"column order matters: equality columns first, then a range column, then "
            f"sort columns."
        )
        expected_impact = "Replaces a full-table scan with a targeted index lookup."
        risks = (_INDEX_WRITE_RISK,)

    return Recommendation(
        problem=(
            f"Queries against {rec.table} filter, join, or sort on ({columns}) but no "
            f"index covers that access pattern, forcing a sequential scan."
        ),
        root_cause=f"{rec.table} has no index PostgreSQL can use for these column(s).",
        technical_explanation=technical_explanation,
        recommended_solution=(
            f"Create the {kind_label} index below on {rec.table} ({columns})."
        ),
        sql_example=rec.create_statement,
        expected_impact=expected_impact,
        confidence=rec.confidence,
        risks=risks,
    )


def _generic(summary: str, confidence: ConfidenceLevel) -> Recommendation:
    """Fallback for a finding code with no template -- keeps the engine
    robust rather than crashing, while a test guards that every real code
    has a template.
    """
    return Recommendation(
        problem=summary,
        root_cause="See the problem description.",
        technical_explanation="A performance issue was detected; details are in the "
        "problem summary.",
        recommended_solution="Review the flagged query and address the issue described.",
        sql_example=None,
        expected_impact="Varies with the specific issue.",
        confidence=confidence,
        risks=(),
    )