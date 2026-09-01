"""Unit tests for sqlcoach.database.explain_runner.

All tests mock psycopg -- no live PostgreSQL needed, matching this
layer's existing testing philosophy from Sprint 2. Real-DB
verification is the skipped stub in test_explain_runner_integration.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import psycopg
import pytest

from sqlcoach.database.explain_runner import ExplainRunner, is_mutating_statement
from sqlcoach.exceptions import (
    DatabaseConnectionError,
    MutatingStatementError,
    ValidationError,
)

class TestIsMutatingStatement:
    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO users (id) VALUES (1)",
            "UPDATE users SET x = 1",
            "DELETE FROM users",
            "DROP TABLE users",
            "TRUNCATE users",
        ],
    )
    def test_detects_mutating_and_ddl_statements(self, sql: str) -> None:
        assert is_mutating_statement(sql) is True

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM users",
            "SELECT 1",
            "WITH x AS (SELECT 1) SELECT * FROM x",
            "SELECT 1 UNION SELECT 2",
        ],
    )
    def test_does_not_flag_read_only_queries(self, sql: str) -> None:
        assert is_mutating_statement(sql) is False

    def test_unparseable_sql_is_treated_as_mutating(self) -> None:
        assert is_mutating_statement("SELEC * FRM broken syntax here") is True

    def test_garbage_that_silently_parses_as_something_else_is_still_blocked(self) -> None:
        # This exact input is the case that exposed a real flaw during
        # development: it doesn't raise a ParseError (sqlglot's lenient
        # grammar reinterprets it as some other expression type, here
        # "Alias") -- an allowlist correctly blocks it anyway, where an
        # earlier denylist-based design incorrectly let it through.
        assert is_mutating_statement("SELEC * FRM broken") is True

    def test_unsupported_syntax_command_fallback_is_treated_as_mutating(self) -> None:
        # sqlglot falls back to a generic "Command" node for syntax it
        # doesn't specifically model (e.g. SHOW). That bucket is
        # ambiguous enough that it should never be treated as safe.
        assert is_mutating_statement("SHOW search_path") is True


def _mock_connection(fetch_result: object) -> MagicMock:
    connection = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = fetch_result
    connection.cursor.return_value.__enter__.return_value = cursor
    return connection


class TestMutationGuard:
    def test_blocks_mutating_statement_by_default(self) -> None:
        connection = _mock_connection(None)
        runner = ExplainRunner()

        with pytest.raises(MutatingStatementError):
            runner.explain(connection, "DELETE FROM users")

        connection.cursor.assert_not_called()

    def test_allows_mutating_statement_when_confirmed(self) -> None:
        fake_payload = [{"Plan": {"Node Type": "Delete"}}]
        connection = _mock_connection((fake_payload,))
        runner = ExplainRunner()

        result = runner.explain(connection, "DELETE FROM users", confirm_mutations=True)

        assert result == fake_payload

    def test_does_not_block_select(self) -> None:
        fake_payload = [{"Plan": {"Node Type": "Seq Scan"}}]
        connection = _mock_connection((fake_payload,))
        runner = ExplainRunner()

        result = runner.explain(connection, "SELECT * FROM users")

        assert result == fake_payload


class TestExplainExecution:
    def test_sets_statement_timeout_before_explain(self) -> None:
        fake_payload = [{"Plan": {"Node Type": "Seq Scan"}}]
        connection = _mock_connection((fake_payload,))
        cursor = connection.cursor.return_value.__enter__.return_value
        runner = ExplainRunner(statement_timeout_seconds=5)

        runner.explain(connection, "SELECT 1")

        first_call_sql = cursor.execute.call_args_list[0].args[0]
        assert "statement_timeout" in first_call_sql
        assert "5000" in first_call_sql  # 5 seconds -> 5000 ms

    def test_runs_explain_analyze_buffers_format_json(self) -> None:
        fake_payload = [{"Plan": {"Node Type": "Seq Scan"}}]
        connection = _mock_connection((fake_payload,))
        cursor = connection.cursor.return_value.__enter__.return_value
        runner = ExplainRunner()

        runner.explain(connection, "SELECT 1")

        second_call_sql = cursor.execute.call_args_list[1].args[0]
        assert "EXPLAIN" in second_call_sql
        assert "ANALYZE" in second_call_sql
        assert "BUFFERS" in second_call_sql
        assert "FORMAT JSON" in second_call_sql
        assert "SELECT 1" in second_call_sql

    def test_returns_the_json_payload_directly(self) -> None:
        fake_payload = [{"Plan": {"Node Type": "Seq Scan"}, "Planning Time": 0.5}]
        connection = _mock_connection((fake_payload,))
        runner = ExplainRunner()

        result = runner.explain(connection, "SELECT 1")

        assert result == fake_payload


class TestErrorHandling:
    def test_wraps_psycopg_error(self) -> None:
        connection = MagicMock()
        connection.cursor.return_value.__enter__.side_effect = psycopg.Error("boom")
        runner = ExplainRunner()

        with pytest.raises(DatabaseConnectionError):
            runner.explain(connection, "SELECT 1")

    def test_no_row_returned_raises_database_error(self) -> None:
        connection = _mock_connection(None)
        runner = ExplainRunner()

        with pytest.raises(DatabaseConnectionError):
            runner.explain(connection, "SELECT 1")



class TestWriteDetectionBeyondRootNode:
    """A root-node-only check is not enough: PostgreSQL executes
    data-modifying CTEs for real under EXPLAIN ANALYZE, and sqlglot
    parses them as a plain Select.
    """

    @pytest.mark.parametrize(
        "sql",
        [
            "WITH d AS (DELETE FROM users WHERE id = 1 RETURNING *) SELECT * FROM d",
            "WITH i AS (INSERT INTO audit (id) VALUES (1) RETURNING *) SELECT * FROM i",
            "WITH u AS (UPDATE users SET name = 'x' RETURNING *) SELECT * FROM u",
        ],
    )
    def test_data_modifying_cte_is_treated_as_mutating(self, sql: str) -> None:
        assert is_mutating_statement(sql) is True

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM users FOR UPDATE",
            "SELECT * FROM users FOR SHARE",
        ],
    )
    def test_row_locking_select_is_treated_as_mutating(self, sql: str) -> None:
        assert is_mutating_statement(sql) is True

    @pytest.mark.parametrize(
        "sql",
        [
            "WITH x AS (SELECT 1) SELECT * FROM x",
            "SELECT * FROM (SELECT id FROM orders) AS s",
            "SELECT * FROM t WHERE id IN (SELECT id FROM u)",
        ],
    )
    def test_read_only_nesting_is_not_flagged(self, sql: str) -> None:
        assert is_mutating_statement(sql) is False

    def test_explain_blocks_a_data_modifying_cte_without_touching_the_database(
        self,
    ) -> None:
        connection = MagicMock()
        runner = ExplainRunner()

        with pytest.raises(MutatingStatementError):
            runner.explain(
                connection,
                "WITH d AS (DELETE FROM users RETURNING *) SELECT * FROM d",
            )

        connection.cursor.assert_not_called()


class TestStatementTimeoutValidation:
    @pytest.mark.parametrize("seconds", [0, -1])
    def test_rejects_non_positive_timeout(self, seconds: int) -> None:
        # PostgreSQL reads `statement_timeout = 0` as "no timeout", so
        # silently accepting 0 would disable the very guard it configures.
        with pytest.raises(ValidationError):
            ExplainRunner(statement_timeout_seconds=seconds)