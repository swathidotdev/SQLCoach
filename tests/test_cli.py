"""Unit tests for sqlcoach.cli.main."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from sqlcoach.cli.main import app
from sqlcoach.exceptions import (
    DatabaseConnectionError,
    ParsingError,
    SQLCoachError,
)

runner = CliRunner()


class TestHelp:
    def test_help_lists_all_planned_commands(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for command_name in ("analyze", "audit", "report", "compare"):
            assert command_name in result.output


class TestStubCommands:
    # def test_analyze_prints_not_yet_implemented_and_exits_zero(self) -> None:
    #     result = runner.invoke(app, ["analyze"])
    #     assert result.exit_code == 0
    #     assert "not yet implemented" in result.output

    def test_audit_prints_not_yet_implemented_and_exits_zero(self) -> None:
        result = runner.invoke(app, ["audit"])
        assert result.exit_code == 0
        assert "not yet implemented" in result.output

    def test_report_prints_not_yet_implemented_and_exits_zero(self) -> None:
        result = runner.invoke(app, ["report"])
        assert result.exit_code == 0
        assert "not yet implemented" in result.output




class TestJsonLogsFlag:
    def test_json_logs_flag_is_accepted(self) -> None:
        result = runner.invoke(app, ["--json-logs", "audit"])
        assert result.exit_code == 0


class TestConfigErrorHandling:
    def test_invalid_config_file_causes_clean_exit_with_error(self, tmp_path: Path) -> None:
        bad_config = tmp_path / "sqlcoach.toml"
        bad_config.write_text("this is not [ valid toml")

        result = runner.invoke(app, ["--config", str(bad_config), "analyze"])

        assert result.exit_code == 1
        assert "Configuration error" in result.output

    def test_missing_config_file_falls_back_to_defaults(self, tmp_path: Path) -> None:
        missing_config = tmp_path / "does_not_exist.toml"

        result = runner.invoke(app, ["--config", str(missing_config), "audit"])

        assert result.exit_code == 0
        assert "not yet implemented" in result.output


class TestDomainErrorHandling:
    """FR-2.9: domain errors become a clean message plus a stable exit
    code, never a traceback.
    """

    def test_domain_error_from_a_service_exits_with_its_mapped_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def failing_service(*_args: object, **_kwargs: object) -> None:
            raise DatabaseConnectionError("Could not connect to PostgreSQL")

        monkeypatch.setattr("sqlcoach.cli.main.analyze_service", failing_service)

        result = runner.invoke(app, ["analyze"])

        assert result.exit_code == 5
        assert result.exception is None or isinstance(result.exception, SystemExit)

    def test_different_error_types_get_different_exit_codes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def failing_service(*_args: object, **_kwargs: object) -> None:
            raise ParsingError("queries.sql is not valid SQL")

        monkeypatch.setattr("sqlcoach.cli.main.analyze_service", failing_service)

        result = runner.invoke(app, ["analyze"])

        assert result.exit_code == 4

    def test_unmapped_domain_error_falls_back_to_exit_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def failing_service(*_args: object, **_kwargs: object) -> None:
            raise SQLCoachError("something went wrong")

        monkeypatch.setattr("sqlcoach.cli.main.analyze_service", failing_service)

        result = runner.invoke(app, ["analyze"])

        assert result.exit_code == 1

    

class TestAnalyzeCommand:
    def test_missing_source_exits_with_validation_code(self) -> None:
        result = runner.invoke(app, ["analyze"])
        assert result.exit_code == 3

    def test_static_parse_without_db_url(self, tmp_path: Path) -> None:
        source = tmp_path / "q.sql"
        source.write_text("SELECT 1;\nSELECT * FROM users WHERE id = 5;\n")

        result = runner.invoke(app, ["analyze", str(source)])

        assert result.exit_code == 0
        assert "Parsed 2 query(ies)." in result.output
        # assert "No --db-url given" in result.output
        assert "Pass --db-url" in result.output

    def test_renders_recommendations_from_the_service(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sqlcoach.models.recommendation import ConfidenceLevel, Recommendation
        from sqlcoach.reports.services import AnalyzeResult

        def fake_service(*_args: object, **_kwargs: object) -> AnalyzeResult:
            return AnalyzeResult(
                queries_parsed=1,
                queries_analyzed=1,
                analyzed_against_database=True,
                recommendations=(
                    Recommendation(
                        problem="Sequential scan on users",
                        root_cause="No index on users.email",
                        technical_explanation="A seq scan reads every row.",
                        recommended_solution="Create the index below on users (email).",
                        sql_example="CREATE INDEX idx_users_email ON users (email);",
                        expected_impact="Index lookup instead of full scan.",
                        confidence=ConfidenceLevel.HIGH,
                        risks=("Adds write overhead.",),
                    ),
                ),
            )

        monkeypatch.setattr("sqlcoach.cli.main.analyze_service", fake_service)

        result = runner.invoke(app, ["analyze", "x.sql", "--db-url", "postgresql://x/y"])

        assert result.exit_code == 0
        assert "1 recommendation(s)" in result.output
        assert "CREATE INDEX idx_users_email ON users (email);" in result.output
        assert "[High confidence]" in result.output
class TestCompareCommand:
    def test_missing_sources_exit_validation(self) -> None:
        result = runner.invoke(app, ["compare"])
        assert result.exit_code == 3

    def test_static_compare_renders_diff(self, tmp_path: Path) -> None:
        before = tmp_path / "b.sql"
        before.write_text("SELECT * FROM users WHERE email = 'a';")
        after = tmp_path / "a.sql"
        after.write_text("SELECT id FROM users WHERE email = 'a';")

        result = runner.invoke(app, ["compare", str(before), str(after)])

        assert result.exit_code == 0
        assert "Anti-patterns:" in result.output
        assert "Verdict:" in result.output