"""Coverage for the index-catalog readers' error-wrapping (Sprint 12)."""

from __future__ import annotations

from unittest.mock import MagicMock

import psycopg
import pytest

from sqlcoach.database.index_catalog import fetch_index_usage, fetch_indexes
from sqlcoach.exceptions import DatabaseConnectionError


def _connection_that_errors() -> MagicMock:
    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    cursor.execute.side_effect = psycopg.Error("boom")
    return connection


class TestCatalogReaderErrorWrapping:
    def test_fetch_indexes_wraps_driver_error(self) -> None:
        with pytest.raises(DatabaseConnectionError):
            fetch_indexes(_connection_that_errors())

    def test_fetch_index_usage_wraps_driver_error(self) -> None:
        with pytest.raises(DatabaseConnectionError):
            fetch_index_usage(_connection_that_errors())