"""Integration test stub for ExplainRunner against a real PostgreSQL instance.

Written now per the Sprint 4 task list, but skipped until Phase 5
provides a dockerized Postgres for CI. This documents the intended
real-DB verification without requiring a live database in every
developer's environment or in this sprint's CI run.
"""

from __future__ import annotations

import pytest

from sqlcoach.database.connection import DatabaseConnection
from sqlcoach.database.explain_runner import ExplainRunner


@pytest.mark.integration
@pytest.mark.skip(reason="Requires a live PostgreSQL instance; see Phase 5 for the dockerized test setup.")
def test_explain_runner_against_real_postgres() -> None:
    with DatabaseConnection(dsn="postgresql://postgres@localhost/postgres") as conn:
        runner = ExplainRunner()
        result = runner.explain(conn, "SELECT 1")
        assert result[0]["Plan"]["Node Type"] == "Result"