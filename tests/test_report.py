"""Unit tests for sqlcoach.models.report."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from sqlcoach.models.query import Query, QuerySource
from sqlcoach.models.recommendation import ConfidenceLevel, Recommendation
from sqlcoach.models.report import Report


class TestDefaults:
    def test_empty_report_has_sensible_defaults(self) -> None:
        report = Report()
        assert report.queries_analyzed == ()
        assert report.recommendations == ()
        assert report.source_description is None

    def test_generated_at_defaults_to_now(self) -> None:
        before = datetime.now(timezone.utc) - timedelta(seconds=5)
        report = Report()
        after = datetime.now(timezone.utc) + timedelta(seconds=5)
        assert before <= report.generated_at <= after


class TestAggregation:
    def test_report_aggregates_queries_and_recommendations(self) -> None:
        query = Query(text="SELECT * FROM users;", source=QuerySource.SQL_FILE)
        recommendation = Recommendation(
            problem="SELECT * usage",
            root_cause="All columns requested unnecessarily",
            technical_explanation="Wider row reads increase I/O and network transfer.",
            recommended_solution="Select only the needed columns",
            expected_impact="Minor reduction in I/O",
            confidence=ConfidenceLevel.MEDIUM,
        )
        report = Report(
            queries_analyzed=(query,),
            recommendations=(recommendation,),
            source_description="queries.sql",
        )
        assert len(report.queries_analyzed) == 1
        assert len(report.recommendations) == 1
        assert report.source_description == "queries.sql"


class TestValidation:
    def test_unknown_field_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Report(bogus_field="oops")


class TestImmutability:
    def test_report_is_frozen(self) -> None:
        report = Report()
        with pytest.raises(ValidationError):
            report.source_description = "changed"  # type: ignore[misc]