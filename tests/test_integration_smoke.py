"""Smoke test proving the integration harness connects to a real DB.

Skipped automatically when SQLCOACH_TEST_DB_URL is unset.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_can_connect_and_query(db_connection) -> None:
    with db_connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone()[0] == 1


def test_server_is_postgres(db_connection) -> None:
    with db_connection.cursor() as cursor:
        cursor.execute("SELECT version()")
        assert "PostgreSQL" in cursor.fetchone()[0]