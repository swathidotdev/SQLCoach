"""Unit tests for sqlcoach.models.query."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sqlcoach.models.query import Query, QuerySource


class TestValidConstruction:
    def test_minimal_valid_query(self) -> None:
        query = Query(text="SELECT 1;", source=QuerySource.SQL_FILE)
        assert query.text == "SELECT 1;"
        assert query.source is QuerySource.SQL_FILE
        assert query.call_count == 1
        assert query.execution_time_ms is None

    def test_full_valid_query(self) -> None:
        query = Query(
            text="SELECT * FROM orders WHERE user_id = 10;",
            source=QuerySource.LOG_FILE,
            source_location="orders.log:42",
            execution_time_ms=820.5,
            call_count=3,
        )
        assert query.source_location == "orders.log:42"
        assert query.execution_time_ms == 820.5
        assert query.call_count == 3


class TestValidation:
    def test_empty_text_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Query(text="   ", source=QuerySource.SQL_FILE)

    def test_negative_execution_time_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Query(text="SELECT 1;", source=QuerySource.SQL_FILE, execution_time_ms=-5)

    def test_call_count_below_one_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Query(text="SELECT 1;", source=QuerySource.SQL_FILE, call_count=0)

    def test_unknown_field_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Query(text="SELECT 1;", source=QuerySource.SQL_FILE, unexpected_field="oops")

    def test_invalid_source_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Query(text="SELECT 1;", source="not_a_real_source")


class TestImmutability:
    def test_query_is_frozen(self) -> None:
        query = Query(text="SELECT 1;", source=QuerySource.SQL_FILE)
        with pytest.raises(ValidationError):
            query.text = "SELECT 2;"  # type: ignore[misc]