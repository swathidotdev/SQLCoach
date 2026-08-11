"""Unit tests for sqlcoach.models.recommendation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sqlcoach.models.recommendation import ConfidenceLevel, Recommendation


def _make_recommendation(**overrides: object) -> Recommendation:
    defaults: dict[str, object] = {
        "problem": "Sequential scan on users.email",
        "root_cause": "No index exists on the filtered column",
        "technical_explanation": (
            "Postgres must read every row in the table to evaluate the filter, "
            "since no index covers users.email."
        ),
        "recommended_solution": "Create a B-tree index on users.email",
        "sql_example": "CREATE INDEX idx_users_email ON users(email);",
        "expected_impact": "Reduces execution time from ~620ms to ~15ms on this workload",
        "confidence": ConfidenceLevel.HIGH,
    }
    defaults.update(overrides)
    return Recommendation(**defaults)  # type: ignore[arg-type]


class TestValidConstruction:
    def test_full_recommendation(self) -> None:
        rec = _make_recommendation(risks=("Adds write overhead", "Uses additional disk space"))
        assert rec.confidence is ConfidenceLevel.HIGH
        assert len(rec.risks) == 2

    def test_sql_example_and_risks_are_optional(self) -> None:
        rec = _make_recommendation(sql_example=None)
        assert rec.sql_example is None
        assert rec.risks == ()


class TestValidation:
    def test_invalid_confidence_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_recommendation(confidence="Extremely Sure")

    def test_missing_required_field_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Recommendation(
                problem="Sequential scan",
                root_cause="No index",
                technical_explanation="...",
                recommended_solution="Add an index",
                confidence=ConfidenceLevel.MEDIUM,
            )  # type: ignore[call-arg]

    def test_unknown_field_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_recommendation(bogus_field="oops")


class TestImmutability:
    def test_recommendation_is_frozen(self) -> None:
        rec = _make_recommendation()
        with pytest.raises(ValidationError):
            rec.confidence = ConfidenceLevel.LOW  # type: ignore[misc]