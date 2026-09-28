"""Unit tests for impact estimation and its engine wiring (Sprint 11)."""

from __future__ import annotations

from sqlcoach.advisor.impact_estimator import estimate_index_impact
from sqlcoach.advisor.recommendation_engine import RecommendationEngine
from sqlcoach.analyzer.base import Finding, Severity
from sqlcoach.models.index_recommendation import IndexKind, IndexRecommendation
from sqlcoach.models.recommendation import ConfidenceLevel


class TestEstimator:
    def test_high_magnitude_for_large_scans(self) -> None:
        estimate = estimate_index_impact(500_000)
        assert estimate.magnitude == "high"
        assert "500,000" in estimate.text
        assert "orders of magnitude" in estimate.text
        assert "Estimate only" in estimate.text

    def test_moderate_magnitude(self) -> None:
        assert estimate_index_impact(5_000).magnitude == "moderate"

    def test_low_magnitude_for_small_tables(self) -> None:
        estimate = estimate_index_impact(50)
        assert estimate.magnitude == "low"
        assert "may already be acceptable" in estimate.text

    def test_never_fabricates_a_time_figure(self) -> None:
        # Honesty guard: the estimate talks about rows, never a fake ms number.
        text = estimate_index_impact(500_000).text.lower()
        assert "ms" not in text
        assert "verify" in text


def _seq(relation: str, rows: int) -> Finding:
    return Finding(
        code="SEQ_SCAN_LARGE_TABLE",
        detector="sequential_scan",
        severity=Severity.HIGH,
        summary=f"seq on {relation}",
        node_type="Seq Scan",
        relation_name=relation,
        metrics={"rows_scanned": rows, "threshold": 10000},
    )


def _index_rec(table: str) -> IndexRecommendation:
    return IndexRecommendation(
        table=table,
        columns=("email",),
        kind=IndexKind.SINGLE_COLUMN,
        create_statement=f"CREATE INDEX x ON {table} (email);",
        rationale="r",
        confidence=ConfidenceLevel.HIGH,
        source_finding_code="SEQ_SCAN_LARGE_TABLE",
    )


class TestEngineImpactEnrichment:
    def test_index_rec_impact_is_quantified_from_seq_scan_rows(self) -> None:
        recs = RecommendationEngine().generate(
            plan_findings=[_seq("users", 500_000)],
            index_recommendations=[_index_rec("users")],
        )
        assert "500,000" in recs[0].expected_impact
        assert "Estimate only" in recs[0].expected_impact

    def test_standalone_seq_scan_impact_is_quantified(self) -> None:
        recs = RecommendationEngine().generate(plan_findings=[_seq("orders", 5_000)])
        assert len(recs) == 1
        assert "5,000" in recs[0].expected_impact

    def test_index_rec_without_matching_rows_keeps_qualitative_impact(self) -> None:
        recs = RecommendationEngine().generate(index_recommendations=[_index_rec("products")])
        assert "Estimate only" not in recs[0].expected_impact
        assert "index lookup" in recs[0].expected_impact.lower()