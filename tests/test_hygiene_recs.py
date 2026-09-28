"""Unit tests for index-hygiene recommendations and the engine's 4th source."""

from __future__ import annotations

from sqlcoach.advisor.anti_patterns.base import AntiPatternFinding
from sqlcoach.advisor.recommendation_builders import from_index_hygiene
from sqlcoach.advisor.recommendation_engine import RecommendationEngine
from sqlcoach.analyzer.base import Severity
from sqlcoach.models.index_hygiene import IndexHygieneFinding
from sqlcoach.models.index_recommendation import IndexKind, IndexRecommendation
from sqlcoach.models.recommendation import ConfidenceLevel


def _hygiene(code: str, confidence: ConfidenceLevel = ConfidenceLevel.HIGH) -> IndexHygieneFinding:
    return IndexHygieneFinding(
        code=code,
        detector="d",
        severity=Severity.MEDIUM,
        confidence=confidence,
        summary=f"{code} on t",
        table="orders",
        index_name="idx_x",
        drop_statement="DROP INDEX idx_x;",
        metrics={},
    )


class TestBuilder:
    def test_duplicate_maps_to_recommendation_with_drop_sql(self) -> None:
        rec = from_index_hygiene(_hygiene("DUPLICATE_INDEX"))
        assert rec.sql_example == "DROP INDEX idx_x;"
        assert rec.confidence is ConfidenceLevel.HIGH
        assert "orders" in rec.root_cause
        assert any("destructive" in risk for risk in rec.risks)

    def test_unused_preserves_medium_confidence(self) -> None:
        rec = from_index_hygiene(_hygiene("UNUSED_INDEX", ConfidenceLevel.MEDIUM))
        assert rec.confidence is ConfidenceLevel.MEDIUM
        assert any("verify" in risk.lower() for risk in rec.risks)


class TestEngineFourthSource:
    def test_hygiene_findings_become_recommendations(self) -> None:
        recs = RecommendationEngine().generate(
            index_hygiene_findings=[_hygiene("DUPLICATE_INDEX")]
        )
        assert len(recs) == 1
        assert recs[0].sql_example == "DROP INDEX idx_x;"

    def test_all_four_sources_unify_and_rank(self) -> None:
        index_rec = IndexRecommendation(
            table="users",
            columns=("email",),
            kind=IndexKind.SINGLE_COLUMN,
            create_statement="CREATE INDEX ix ON users (email);",
            rationale="r",
            confidence=ConfidenceLevel.HIGH,
            source_finding_code="SEQ_SCAN_LARGE_TABLE",
        )
        anti = AntiPatternFinding(
            code="SELECT_STAR",
            detector="d",
            severity=Severity.LOW,
            summary="star",
            source_location="q:1",
            relation_name="users",
        )
        recs = RecommendationEngine().generate(
            index_recommendations=[index_rec],
            anti_pattern_findings=[anti],
            index_hygiene_findings=[_hygiene("UNUSED_INDEX", ConfidenceLevel.MEDIUM)],
        )
        assert recs[0].sql_example.startswith("CREATE INDEX")  # HIGH impact first
        assert recs[-1].problem == "star"  # LOW impact last
        assert len(recs) == 3