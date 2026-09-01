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
        assert query.statement_type is None
        assert query.referenced_tables == ()

    def test_full_valid_query(self) -> None:
        query = Query(
            text="SELECT * FROM orders WHERE user_id = 10;",
            source=QuerySource.LOG_FILE,
            source_location="orders.log:42",
            execution_time_ms=820.5,
            call_count=3,
            statement_type="SELECT",
            referenced_tables=("orders",),
        )
        assert query.source_location == "orders.log:42"
        assert query.execution_time_ms == 820.5
        assert query.call_count == 3
        assert query.statement_type == "SELECT"
        assert query.referenced_tables == ("orders",)


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


class TestWorkloadTimingFields:
    def test_total_execution_time_is_optional(self) -> None:
        query = Query(text="SELECT 1", source=QuerySource.SQL_FILE)
        assert query.total_execution_time_ms is None

    def test_records_mean_and_total_independently(self) -> None:
        query = Query(
            text="SELECT 1",
            source=QuerySource.PG_STAT_STATEMENTS,
            execution_time_ms=2.5,
            total_execution_time_ms=5000.0,
            call_count=2000,
        )
        assert query.execution_time_ms == 2.5
        assert query.total_execution_time_ms == 5000.0

    def test_rejects_negative_total_execution_time(self) -> None:
        with pytest.raises(ValidationError):
            Query(
                text="SELECT 1",
                source=QuerySource.SQL_FILE,
                total_execution_time_ms=-1.0,
            )


class TestFingerprint:
    def test_prefers_normalized_text(self) -> None:
        query = Query(
            text="select  1",
            normalized_text="SELECT 1",
            source=QuerySource.SQL_FILE,
        )
        assert query.fingerprint == "SELECT 1"

    def test_falls_back_to_stripped_raw_text_when_unparsed(self) -> None:
        query = Query(text="  SELEC 1  ", source=QuerySource.LOG_FILE)
        assert query.fingerprint == "SELEC 1"