"""Unit tests for sqlcoach.cli.main."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from sqlcoach.cli.main import app

runner = CliRunner()


class TestHelp:
    def test_help_lists_all_planned_commands(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for command_name in ("analyze", "audit", "report", "compare"):
            assert command_name in result.output


class TestStubCommands:
    def test_analyze_prints_not_yet_implemented_and_exits_zero(self) -> None:
        result = runner.invoke(app, ["analyze"])
        assert result.exit_code == 0
        assert "not yet implemented" in result.output

    def test_audit_prints_not_yet_implemented_and_exits_zero(self) -> None:
        result = runner.invoke(app, ["audit"])
        assert result.exit_code == 0
        assert "not yet implemented" in result.output

    def test_report_prints_not_yet_implemented_and_exits_zero(self) -> None:
        result = runner.invoke(app, ["report"])
        assert result.exit_code == 0
        assert "not yet implemented" in result.output

    def test_compare_prints_not_yet_implemented_and_exits_zero(self) -> None:
        result = runner.invoke(app, ["compare"])
        assert result.exit_code == 0
        assert "not yet implemented" in result.output


class TestJsonLogsFlag:
    def test_json_logs_flag_is_accepted(self) -> None:
        result = runner.invoke(app, ["--json-logs", "analyze"])
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

        result = runner.invoke(app, ["--config", str(missing_config), "analyze"])

        assert result.exit_code == 0
        assert "not yet implemented" in result.output