"""Unit tests for confidence heuristics and recommendation builders (Sprint 9)."""

from __future__ import annotations

import pytest

from sqlcoach.advisor.anti_patterns.base import AntiPatternFinding
from sqlcoach.advisor.confidence import (
    confidence_for_anti_pattern,
    confidence_from_severity,
)
from sqlcoach.advisor.recommendation_builders import (
    _ANTI_PATTERN_TEMPLATES,
    _PLAN_TEMPLATES,
    from_anti_pattern,
    from_index_recommendation,
    from_plan_finding,
)
from sqlcoach.analyzer.base import Finding, Severity
from sqlcoach.models.index_recommendation import IndexKind, IndexRecommendation
from sqlcoach.models.recommendation import ConfidenceLevel


def _plan_finding(code: str, severity: Severity = Severity.HIGH, relation: str = "orders") -> Finding:
    return Finding(
        code=code,
        detector="d",
        severity=severity,
        summary=f"{code} problem",
        node_type="X",
        relation_name=relation,
    )


def _anti_pattern(code: str) -> AntiPatternFinding:
    return AntiPatternFinding(
        code=code,
        detector="d",
        severity=Severity.LOW,
        summary=f"{code} problem",
        source_location="q.sql:line 1",
    )


def _index_rec(
    kind: IndexKind = IndexKind.SINGLE_COLUMN,
    columns: tuple[str, ...] = ("email",),
    included: tuple[str, ...] = (),
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH,
) -> IndexRecommendation:
    statement = f"CREATE INDEX idx_users_{'_'.join(columns)} ON users ({', '.join(columns)})"
    if included:
        statement += f" INCLUDE ({', '.join(included)})"
    return IndexRecommendation(
        table="users",
        columns=columns,
        included_columns=included,
        kind=kind,
        create_statement=statement + ";",
        rationale="Create the index.",
        confidence=confidence,
        source_finding_code="SEQ_SCAN_LARGE_TABLE",
    )


def _has_write_risk(recommendation) -> bool:
    return any("write overhead" in risk for risk in recommendation.risks)


class TestConfidence:
    def test_severity_maps_directly(self) -> None:
        assert confidence_from_severity(Severity.HIGH) is ConfidenceLevel.HIGH
        assert confidence_from_severity(Severity.MEDIUM) is ConfidenceLevel.MEDIUM
        assert confidence_from_severity(Severity.LOW) is ConfidenceLevel.LOW

    def test_anti_patterns_high_except_n_plus_one(self) -> None:
        assert confidence_for_anti_pattern("SELECT_STAR") is ConfidenceLevel.HIGH
        assert confidence_for_anti_pattern("LEADING_WILDCARD_LIKE") is ConfidenceLevel.HIGH
        assert confidence_for_anti_pattern("ORDER_BY_RANDOM") is ConfidenceLevel.HIGH
        assert confidence_for_anti_pattern("N_PLUS_ONE") is ConfidenceLevel.MEDIUM

    def test_unknown_anti_pattern_defaults_to_medium(self) -> None:
        assert confidence_for_anti_pattern("WHATEVER") is ConfidenceLevel.MEDIUM


class TestPlanBuilder:
    def test_all_narrative_fields_are_populated(self) -> None:
        rec = from_plan_finding(_plan_finding("SEQ_SCAN_LARGE_TABLE"))
        assert rec.problem == "SEQ_SCAN_LARGE_TABLE problem"
        assert rec.root_cause and rec.technical_explanation and rec.recommended_solution
        assert rec.expected_impact
        assert rec.confidence is ConfidenceLevel.HIGH
        assert "orders" in rec.root_cause  # {relation} filled
        assert rec.sql_example is None

    def test_estimate_only_finding_is_medium_confidence(self) -> None:
        rec = from_plan_finding(_plan_finding("SEQ_SCAN_LARGE_TABLE", Severity.MEDIUM))
        assert rec.confidence is ConfidenceLevel.MEDIUM

    def test_cardinality_has_no_risks(self) -> None:
        assert from_plan_finding(_plan_finding("CARDINALITY_MISESTIMATION")).risks == ()

    @pytest.mark.parametrize("code", list(_PLAN_TEMPLATES))
    def test_every_plan_code_fully_fills_relation(self, code: str) -> None:
        rec = from_plan_finding(_plan_finding(code))
        combined = (
            rec.root_cause
            + rec.technical_explanation
            + rec.recommended_solution
            + rec.expected_impact
        )
        assert "{relation}" not in combined

    def test_unknown_code_falls_back_without_crashing(self) -> None:
        rec = from_plan_finding(_plan_finding("MYSTERY_CODE"))
        assert rec.problem == "MYSTERY_CODE problem"


class TestAntiPatternBuilder:
    def test_select_star_is_high_confidence_with_no_sql(self) -> None:
        rec = from_anti_pattern(_anti_pattern("SELECT_STAR"))
        assert rec.confidence is ConfidenceLevel.HIGH
        assert rec.sql_example is None
        assert rec.problem == "SELECT_STAR problem"

    def test_n_plus_one_is_medium_confidence(self) -> None:
        assert from_anti_pattern(_anti_pattern("N_PLUS_ONE")).confidence is ConfidenceLevel.MEDIUM

    @pytest.mark.parametrize("code", list(_ANTI_PATTERN_TEMPLATES))
    def test_every_anti_pattern_code_builds(self, code: str) -> None:
        rec = from_anti_pattern(_anti_pattern(code))
        assert rec.problem and rec.root_cause and rec.recommended_solution


class TestIndexBuilder:
    def test_single_column_carries_sql_and_confidence(self) -> None:
        rec = from_index_recommendation(_index_rec())
        assert rec.sql_example == "CREATE INDEX idx_users_email ON users (email);"
        assert rec.confidence is ConfidenceLevel.HIGH
        assert _has_write_risk(rec)
        assert "index-only" not in rec.technical_explanation

    def test_covering_mentions_index_only_and_extra_risk(self) -> None:
        rec = from_index_recommendation(
            _index_rec(IndexKind.COVERING, ("user_id",), ("total", "status"))
        )
        assert "index-only" in rec.technical_explanation
        assert any("INCLUDE" in risk for risk in rec.risks)
        assert "INCLUDE" in rec.sql_example

    def test_confidence_is_preserved_from_the_index_rec(self) -> None:
        rec = from_index_recommendation(_index_rec(confidence=ConfidenceLevel.MEDIUM))
        assert rec.confidence is ConfidenceLevel.MEDIUM


class TestTemplateCoverage:
    def test_all_plan_detector_codes_have_templates(self) -> None:
        required = {
            "SEQ_SCAN_LARGE_TABLE",
            "NESTED_LOOP_LARGE_ROWCOUNT",
            "SORT_SPILLED_TO_DISK",
            "CARDINALITY_MISESTIMATION",
        }
        assert required <= set(_PLAN_TEMPLATES)

    def test_all_anti_pattern_codes_have_templates(self) -> None:
        required = {
            "SELECT_STAR",
            "LEADING_WILDCARD_LIKE",
            "ORDER_BY_RANDOM",
            "N_PLUS_ONE",
        }
        assert required <= set(_ANTI_PATTERN_TEMPLATES)