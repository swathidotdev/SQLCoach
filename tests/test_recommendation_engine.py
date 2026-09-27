"""Unit tests for the recommendation engine: aggregation + ranking (Sprint 9)."""

from __future__ import annotations

from sqlcoach.advisor.anti_patterns.base import AntiPatternFinding
from sqlcoach.advisor.recommendation_engine import RecommendationEngine
from sqlcoach.analyzer.base import Finding, Severity
from sqlcoach.models.index_recommendation import IndexKind, IndexRecommendation
from sqlcoach.models.recommendation import ConfidenceLevel

_ENGINE = RecommendationEngine()


def _plan_finding(code: str, relation: str, severity: Severity = Severity.HIGH) -> Finding:
    return Finding(
        code=code,
        detector="d",
        severity=severity,
        summary=f"{code} on {relation}",
        node_type="X",
        relation_name=relation,
    )


def _anti_pattern(code: str, relation: str | None = None) -> AntiPatternFinding:
    severity = Severity.LOW if code == "SELECT_STAR" else Severity.MEDIUM
    return AntiPatternFinding(
        code=code,
        detector="d",
        severity=severity,
        summary=f"{code}",
        source_location="q.sql:line 1",
        relation_name=relation,
    )


def _index_rec(
    table: str,
    columns: tuple[str, ...] = ("email",),
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH,
) -> IndexRecommendation:
    return IndexRecommendation(
        table=table,
        columns=columns,
        kind=IndexKind.SINGLE_COLUMN,
        create_statement=f"CREATE INDEX x ON {table} ({', '.join(columns)});",
        rationale="Create it.",
        confidence=confidence,
        source_finding_code="SEQ_SCAN_LARGE_TABLE",
    )


class TestAggregation:
    def test_seq_scan_is_folded_into_its_index_rec(self) -> None:
        # Seq scan on 'users' + index rec on 'users' -> ONE recommendation.
        recs = _ENGINE.generate(
            plan_findings=[_plan_finding("SEQ_SCAN_LARGE_TABLE", "users")],
            index_recommendations=[_index_rec("users")],
        )
        assert len(recs) == 1
        assert recs[0].sql_example is not None  # the index recommendation

    def test_seq_scan_without_index_rec_stands_alone(self) -> None:
        recs = _ENGINE.generate(
            plan_findings=[_plan_finding("SEQ_SCAN_LARGE_TABLE", "orders")]
        )
        assert len(recs) == 1
        assert recs[0].sql_example is None  # general advice, no specific SQL

    def test_non_seqscan_finding_is_not_suppressed_by_an_index_rec(self) -> None:
        # A sort spill on 'users' is a different problem from a missing
        # index on 'users' and must survive.
        recs = _ENGINE.generate(
            plan_findings=[_plan_finding("SORT_SPILLED_TO_DISK", "users")],
            index_recommendations=[_index_rec("users")],
        )
        assert len(recs) == 2

    def test_plan_findings_dedup_by_code_and_relation(self) -> None:
        recs = _ENGINE.generate(
            plan_findings=[_plan_finding("SORT_SPILLED_TO_DISK", "t")] * 3
        )
        assert len(recs) == 1
        assert "detected in 3 queries" in recs[0].problem

    def test_anti_patterns_dedup_with_occurrence_count(self) -> None:
        recs = _ENGINE.generate(anti_pattern_findings=[_anti_pattern("SELECT_STAR")] * 50)
        assert len(recs) == 1
        assert "detected in 50 queries" in recs[0].problem

    def test_distinct_relations_stay_separate(self) -> None:
        recs = _ENGINE.generate(
            plan_findings=[
                _plan_finding("SORT_SPILLED_TO_DISK", "a"),
                _plan_finding("SORT_SPILLED_TO_DISK", "b"),
            ]
        )
        assert len(recs) == 2


class TestRanking:
    def test_impact_dominates_frequency(self) -> None:
        # One HIGH-impact sort spill vs 50 LOW-impact SELECT *: the spill wins.
        recs = _ENGINE.generate(
            plan_findings=[_plan_finding("SORT_SPILLED_TO_DISK", "t")],
            anti_pattern_findings=[_anti_pattern("SELECT_STAR")] * 50,
        )
        assert recs[0].problem.startswith("SORT_SPILLED_TO_DISK")

    def test_index_recs_rank_at_the_top(self) -> None:
        recs = _ENGINE.generate(
            index_recommendations=[_index_rec("users")],
            anti_pattern_findings=[_anti_pattern("SELECT_STAR")],
        )
        assert recs[0].sql_example is not None  # index rec first

    def test_frequency_breaks_ties_within_a_tier(self) -> None:
        recs = _ENGINE.generate(
            anti_pattern_findings=[_anti_pattern("ORDER_BY_RANDOM")] * 5
            + [_anti_pattern("LEADING_WILDCARD_LIKE")]
        )
        assert "ORDER_BY_RANDOM" in recs[0].problem

    def test_output_is_deterministic(self) -> None:
        args = dict(
            plan_findings=[
                _plan_finding("SORT_SPILLED_TO_DISK", "a"),
                _plan_finding("CARDINALITY_MISESTIMATION", "b"),
            ],
            index_recommendations=[_index_rec("users"), _index_rec("orders")],
            anti_pattern_findings=[
                _anti_pattern("SELECT_STAR"),
                _anti_pattern("N_PLUS_ONE", "t"),
            ],
        )
        first = [r.problem for r in _ENGINE.generate(**args)]
        second = [r.problem for r in _ENGINE.generate(**args)]
        assert first == second


class TestEmpty:
    def test_no_findings_yields_no_recommendations(self) -> None:
        assert _ENGINE.generate() == []