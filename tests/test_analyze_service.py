"""Unit tests for the analyze application service (Sprint 6 wiring).

The database is always mocked -- no live PostgreSQL is required. These
tests verify the orchestration: parse -> (optionally) EXPLAIN + analyze
-> collect findings, including per-query resilience.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sqlcoach.config import Settings
from sqlcoach.exceptions import (
    DatabaseConnectionError,
    MutatingStatementError,
    ValidationError,
)
from sqlcoach.reports import services
from sqlcoach.reports.services import analyze_service


_LARGE_SEQ_SCAN_PLAN = [
    {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Total Cost": 5000.0,
            "Plan Rows": 500_000,
            "Actual Rows": 500_000,
        },
        "Execution Time": 120.0,
    }
]


def _write_sql(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "queries.sql"
    path.write_text(text, encoding="utf-8")
    return path


class TestSourceValidation:
    def test_missing_source_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            analyze_service(None, settings=Settings())


class TestStaticParseOnly:
    def test_without_db_url_parses_but_does_not_analyze(
        self, tmp_path: Path
    ) -> None:
        source = _write_sql(
            tmp_path, "SELECT 1;\nSELECT * FROM users WHERE id = 5;\n"
        )

        result = analyze_service(source, settings=Settings())

        assert result.queries_parsed == 2
        assert result.queries_analyzed == 0
        assert result.analyzed_against_database is False
        assert result.findings == ()


class TestAgainstDatabase:
    def test_runs_explain_and_returns_findings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = _write_sql(tmp_path, "SELECT * FROM users;")

        connection = MagicMock()
        # DatabaseConnection is a context manager yielding the connection.
        db_cm = MagicMock()
        db_cm.__enter__.return_value = connection
        db_cm.__exit__.return_value = False
        monkeypatch.setattr(services, "DatabaseConnection", lambda **_: db_cm)

        runner = MagicMock()
        runner.explain.return_value = _LARGE_SEQ_SCAN_PLAN
        monkeypatch.setattr(services, "ExplainRunner", lambda: runner)

        result = analyze_service(
            source, db_url="postgresql://localhost/db", settings=Settings()
        )

        assert result.analyzed_against_database is True
        assert result.queries_analyzed == 1
        assert len(result.findings) == 1
        assert result.findings[0].code == "SEQ_SCAN_LARGE_TABLE"
        runner.explain.assert_called_once()

    def test_mutating_statement_is_skipped_without_confirmation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = _write_sql(tmp_path, "SELECT * FROM users;")

        connection = MagicMock()
        db_cm = MagicMock()
        db_cm.__enter__.return_value = connection
        db_cm.__exit__.return_value = False
        monkeypatch.setattr(services, "DatabaseConnection", lambda **_: db_cm)

        runner = MagicMock()
        runner.explain.side_effect = MutatingStatementError("blocked")
        monkeypatch.setattr(services, "ExplainRunner", lambda: runner)

        result = analyze_service(
            source, db_url="postgresql://localhost/db", settings=Settings()
        )

        # The run completes; the blocked query is simply not analyzed.
        assert result.queries_parsed == 1
        assert result.queries_analyzed == 0
        assert result.findings == ()

    def test_per_query_explain_failure_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = _write_sql(tmp_path, "SELECT 1;\nSELECT 2;\n")

        connection = MagicMock()
        db_cm = MagicMock()
        db_cm.__enter__.return_value = connection
        db_cm.__exit__.return_value = False
        monkeypatch.setattr(services, "DatabaseConnection", lambda **_: db_cm)

        runner = MagicMock()
        # First query errors, second succeeds.
        runner.explain.side_effect = [
            DatabaseConnectionError("statement timeout"),
            _LARGE_SEQ_SCAN_PLAN,
        ]
        monkeypatch.setattr(services, "ExplainRunner", lambda: runner)

        result = analyze_service(
            source, db_url="postgresql://localhost/db", settings=Settings()
        )

        assert result.queries_parsed == 2
        assert result.queries_analyzed == 1
        assert len(result.findings) == 1


class TestIndexRecommendationsInPipeline:
    def test_filtered_query_produces_a_recommendation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = _write_sql(tmp_path, "SELECT * FROM users WHERE email = 'a@b.com';")

        connection = MagicMock()
        db_cm = MagicMock()
        db_cm.__enter__.return_value = connection
        db_cm.__exit__.return_value = False
        monkeypatch.setattr(services, "DatabaseConnection", lambda **_: db_cm)

        runner = MagicMock()
        runner.explain.return_value = _LARGE_SEQ_SCAN_PLAN
        monkeypatch.setattr(services, "ExplainRunner", lambda: runner)

        result = analyze_service(
            source, db_url="postgresql://localhost/db", settings=Settings()
        )

        assert len(result.index_recommendations) == 1
        rec = result.index_recommendations[0]
        assert rec.table == "users"
        assert rec.columns == ("email",)
        assert rec.create_statement == "CREATE INDEX idx_users_email ON users (email);"

    def test_unfiltered_query_yields_no_recommendation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = _write_sql(tmp_path, "SELECT * FROM users;")

        connection = MagicMock()
        db_cm = MagicMock()
        db_cm.__enter__.return_value = connection
        db_cm.__exit__.return_value = False
        monkeypatch.setattr(services, "DatabaseConnection", lambda **_: db_cm)

        runner = MagicMock()
        runner.explain.return_value = _LARGE_SEQ_SCAN_PLAN
        monkeypatch.setattr(services, "ExplainRunner", lambda: runner)

        result = analyze_service(
            source, db_url="postgresql://localhost/db", settings=Settings()
        )

        assert result.index_recommendations == ()

    def test_static_parse_has_no_recommendations(self, tmp_path: Path) -> None:
        source = _write_sql(tmp_path, "SELECT * FROM users WHERE email = 'a@b.com';")
        result = analyze_service(source, settings=Settings())
        assert result.index_recommendations == ()