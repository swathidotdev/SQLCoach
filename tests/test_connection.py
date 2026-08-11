"""Unit tests for sqlcoach.database.connection.

All tests here mock psycopg.connect -- per NFR-3.3-style discipline,
this layer must be independently unit-testable without a live
PostgreSQL instance. Real-DB verification is deferred to Phase 5.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import psycopg
import pytest

from sqlcoach.database.connection import DatabaseConnection
from sqlcoach.exceptions import DatabaseConnectionError


class TestConstructionValidation:
    def test_requires_dsn_or_host(self) -> None:
        with pytest.raises(ValueError):
            DatabaseConnection()

    def test_rejects_both_dsn_and_host(self) -> None:
        with pytest.raises(ValueError):
            DatabaseConnection(dsn="postgresql://localhost/db", host="localhost")


class TestDsnConnection:
    @patch("sqlcoach.database.connection.psycopg.connect")
    def test_connects_using_dsn(self, mock_connect: MagicMock) -> None:
        mock_connect.return_value = MagicMock()
        db = DatabaseConnection(dsn="postgresql://user@localhost/mydb")

        with db as conn:
            assert conn is mock_connect.return_value

        mock_connect.assert_called_once_with(
            conninfo="postgresql://user@localhost/mydb", connect_timeout=10
        )


class TestDiscreteParamConnection:
    @patch("sqlcoach.database.connection.psycopg.connect")
    def test_connects_using_discrete_params(self, mock_connect: MagicMock) -> None:
        mock_connect.return_value = MagicMock()
        db = DatabaseConnection(
            host="localhost", port=5433, user="alice", password="secret", dbname="mydb"
        )

        with db as conn:
            assert conn is mock_connect.return_value

        mock_connect.assert_called_once_with(
            host="localhost",
            port=5433,
            user="alice",
            password="secret",
            dbname="mydb",
            connect_timeout=10,
        )

    @patch("sqlcoach.database.connection.psycopg.connect")
    def test_sslmode_included_when_provided(self, mock_connect: MagicMock) -> None:
        mock_connect.return_value = MagicMock()
        db = DatabaseConnection(host="localhost", dbname="mydb", sslmode="require")

        with db:
            pass

        _, kwargs = mock_connect.call_args
        assert kwargs["sslmode"] == "require"

    @patch("sqlcoach.database.connection.psycopg.connect")
    def test_sslmode_omitted_when_not_provided(self, mock_connect: MagicMock) -> None:
        mock_connect.return_value = MagicMock()
        db = DatabaseConnection(host="localhost", dbname="mydb")

        with db:
            pass

        _, kwargs = mock_connect.call_args
        assert "sslmode" not in kwargs


class TestConnectionFailure:
    @patch("sqlcoach.database.connection.psycopg.connect")
    def test_wraps_connection_error(self, mock_connect: MagicMock) -> None:
        original_error = psycopg.OperationalError("connection refused")
        mock_connect.side_effect = original_error
        db = DatabaseConnection(dsn="postgresql://localhost/mydb")

        with pytest.raises(DatabaseConnectionError) as exc_info:
            with db:
                pass

        assert exc_info.value.__cause__ is original_error

    @patch("sqlcoach.database.connection.psycopg.connect")
    def test_never_raises_raw_psycopg_error(self, mock_connect: MagicMock) -> None:
        mock_connect.side_effect = psycopg.Error("generic failure")
        db = DatabaseConnection(dsn="postgresql://localhost/mydb")

        with pytest.raises(DatabaseConnectionError):
            with db:
                pass


class TestCleanup:
    @patch("sqlcoach.database.connection.psycopg.connect")
    def test_connection_closed_on_normal_exit(self, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        db = DatabaseConnection(dsn="postgresql://localhost/mydb")

        with db:
            pass

        mock_conn.close.assert_called_once()

    @patch("sqlcoach.database.connection.psycopg.connect")
    def test_connection_closed_even_if_block_raises(self, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        db = DatabaseConnection(dsn="postgresql://localhost/mydb")

        with pytest.raises(RuntimeError):
            with db:
                raise RuntimeError("something went wrong inside the block")

        mock_conn.close.assert_called_once()