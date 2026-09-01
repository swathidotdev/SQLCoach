"""Unit tests for sqlcoach.database.pg_stat_statements.

All tests mock psycopg -- no live PostgreSQL needed, consistent with
this layer's existing testing philosophy. Real-DB verification of
extension availability and column names is deferred to Phase 5.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import psycopg
import pytest

from sqlcoach.database.pg_stat_statements import (
    fetch_top_queries,
    is_pg_stat_statements_available,
)
from sqlcoach.exceptions import DatabaseConnectionError, ValidationError
from sqlcoach.models.query import QuerySource


def _mock_connection() -> tuple[MagicMock, MagicMock]:
    """Return (connection, cursor) where `cursor` is the shared mock
    returned by every `with connection.cursor() as cursor:` block.
    """
    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    return connection, cursor


class TestAvailabilityCheck:
    def test_returns_true_when_extension_row_found(self) -> None:
        connection, cursor = _mock_connection()
        cursor.fetchone.return_value = (1,)

        assert is_pg_stat_statements_available(connection) is True

    def test_returns_false_when_no_row_found(self) -> None:
        connection, cursor = _mock_connection()
        cursor.fetchone.return_value = None

        assert is_pg_stat_statements_available(connection) is False

    def test_wraps_psycopg_error(self) -> None:
        connection = MagicMock()
        connection.cursor.return_value.__enter__.side_effect = psycopg.Error("boom")

        with pytest.raises(DatabaseConnectionError):
            is_pg_stat_statements_available(connection)


class TestFetchTopQueriesWhenUnavailable:
    def test_returns_empty_list_without_raising(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        connection, cursor = _mock_connection()
        cursor.fetchone.return_value = None  # extension not installed

        with caplog.at_level("WARNING"):
            results = fetch_top_queries(connection)

        assert results == []
        assert any("not enabled" in message for message in caplog.messages)

    def test_does_not_query_pg_stat_statements_table_when_unavailable(self) -> None:
        connection, cursor = _mock_connection()
        cursor.fetchone.return_value = None

        fetch_top_queries(connection)

        # Only the availability check should have run -- one execute call.
        assert cursor.execute.call_count == 1


class TestFetchTopQueriesWhenAvailable:
    def test_maps_rows_to_query_objects(self) -> None:
        connection, cursor = _mock_connection()
        cursor.fetchone.return_value = (1,)  # extension available
        cursor.fetchall.return_value = [
            ("SELECT * FROM orders WHERE user_id = $1", 42, 1000.0, 23.8),
        ]

        results = fetch_top_queries(connection)

        assert len(results) == 1
        query = results[0]
        assert query.source is QuerySource.PG_STAT_STATEMENTS
        assert query.call_count == 42
        assert query.execution_time_ms == 23.8
        assert query.statement_type == "SELECT"
        assert query.referenced_tables == ("orders",)

    def test_uses_limit_in_query(self) -> None:
        connection, cursor = _mock_connection()
        cursor.fetchone.return_value = (1,)
        cursor.fetchall.return_value = []

        fetch_top_queries(connection, limit=10)

        stats_call = cursor.execute.call_args_list[1]
        assert stats_call.args[1] == (10,)

    def test_rejects_limit_below_one(self) -> None:
        connection, _ = _mock_connection()

        with pytest.raises(ValidationError):
            fetch_top_queries(connection, limit=0)

    def test_skips_rows_with_empty_query_text(self) -> None:
        connection, cursor = _mock_connection()
        cursor.fetchone.return_value = (1,)
        cursor.fetchall.return_value = [
            ("", 5, 10.0, 2.0),
            ("SELECT 1", 3, 5.0, 1.5),
        ]

        results = fetch_top_queries(connection)

        assert len(results) == 1
        assert results[0].text == "SELECT 1"

    def test_wraps_psycopg_error_from_stats_query(self) -> None:
        connection, cursor = _mock_connection()
        cursor.fetchone.return_value = (1,)
        cursor.execute.side_effect = [None, psycopg.Error("boom")]

        with pytest.raises(DatabaseConnectionError):
            fetch_top_queries(connection)


class TestTimingFieldMapping:
    def test_preserves_both_mean_and_total_execution_time(self) -> None:
        connection, cursor = _mock_connection()
        cursor.fetchone.return_value = (1,)
        cursor.fetchall.return_value = [
            ("SELECT * FROM orders WHERE user_id = $1", 2000, 5000.0, 2.5),
        ]

        results = fetch_top_queries(connection)

        assert len(results) == 1
        assert results[0].execution_time_ms == 2.5
        assert results[0].total_execution_time_ms == 5000.0
        assert results[0].call_count == 2000

    def test_populates_normalized_text_for_fingerprinting(self) -> None:
        connection, cursor = _mock_connection()
        cursor.fetchone.return_value = (1,)
        cursor.fetchall.return_value = [("select  *  from  orders", 1, 1.0, 1.0)]

        results = fetch_top_queries(connection)

        assert results[0].text == "select  *  from  orders"
        assert results[0].normalized_text == "SELECT * FROM orders"

    def test_skips_rows_with_non_positive_call_count(self) -> None:
        # A statistics reset racing this read could otherwise leak a raw
        # pydantic error (call_count has a ge=1 constraint) out of the
        # database layer.
        connection, cursor = _mock_connection()
        cursor.fetchone.return_value = (1,)
        cursor.fetchall.return_value = [
            ("SELECT 1", 0, 0.0, 0.0),
            ("SELECT 2", 3, 9.0, 3.0),
        ]

        results = fetch_top_queries(connection)

        assert [r.text for r in results] == ["SELECT 2"]