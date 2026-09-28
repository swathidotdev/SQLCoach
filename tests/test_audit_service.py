"""Unit tests for the audit service (Sprint 11)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sqlcoach.config import Settings
from sqlcoach.exceptions import ValidationError
from sqlcoach.reports import audit_service as audit_module
from sqlcoach.reports.audit_service import audit_service

_MUTATING_KEYWORDS = ("INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "CREATE", "ALTER")


def _mock_connection(monkeypatch, *, pg_stat_available: bool, executed: list):
    """Wire a fake DatabaseConnection whose cursor records every execute()."""
    cursor = MagicMock()

    def record_execute(sql, *args, **kwargs):
        executed.append(sql)

    cursor.execute.side_effect = record_execute
    # Availability check -> one row if available, else None.
    cursor.fetchone.return_value = (1,) if pg_stat_available else None
    cursor.fetchall.return_value = []  # no top queries, no indexes, no usage

    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor

    db_cm = MagicMock()
    db_cm.__enter__.return_value = connection
    db_cm.__exit__.return_value = False
    monkeypatch.setattr(audit_module, "DatabaseConnection", lambda **_: db_cm)
    return cursor


class TestValidation:
    def test_missing_db_url_raises(self) -> None:
        with pytest.raises(ValidationError):
            audit_service(None, settings=Settings())


class TestGracefulDegradation:
    def test_workload_skipped_when_pg_stat_statements_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_connection(monkeypatch, pg_stat_available=False, executed=[])

        result = audit_service("postgresql://x/y", settings=Settings())

        skipped_names = {s.name for s in result.sections_skipped}
        assert "workload" in skipped_names
        # Index hygiene still ran (catalog reads returned empty, but ran).
        assert "duplicate_indexes" in result.sections_completed

    def test_workload_runs_when_extension_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_connection(monkeypatch, pg_stat_available=True, executed=[])
        result = audit_service("postgresql://x/y", settings=Settings())
        assert "workload" in result.sections_completed


class TestReadOnlySafety:
    def test_audit_issues_no_mutating_statements(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        executed: list[str] = []
        _mock_connection(monkeypatch, pg_stat_available=True, executed=executed)

        audit_service("postgresql://x/y", settings=Settings())

        for sql in executed:
            first_word = sql.strip().split(None, 1)[0].upper() if sql.strip() else ""
            assert first_word not in _MUTATING_KEYWORDS, f"audit issued a write: {sql!r}"