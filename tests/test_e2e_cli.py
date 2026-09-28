"""End-to-end CLI tests (Sprint 12, US12.3).

Invoke the real CLI as a user would, via Typer's CliRunner, against
fixture files -- covering command wiring, exit codes, and the rendered
output for analyze, compare, and report. Static-only (no database), so
these always run.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from sqlcoach.cli.main import app

runner = CliRunner()


def _write(tmp_path: Path, name: str, sql: str) -> Path:
    path = tmp_path / name
    path.write_text(sql, encoding="utf-8")
    return path


class TestAnalyzeEndToEnd:
    def test_analyze_renders_full_recommendation(self, tmp_path: Path) -> None:
        source = _write(
            tmp_path, "q.sql", "SELECT * FROM users WHERE name LIKE '%x';"
        )

        result = runner.invoke(app, ["analyze", str(source)])

        assert result.exit_code == 0
        assert "Parsed 1 query(ies)." in result.output
        assert "recommendation(s)" in result.output
        # The renderer emits each narrative field.
        assert "Root cause:" in result.output
        assert "Fix:" in result.output
        assert "Impact:" in result.output
        assert "confidence]" in result.output

    def test_analyze_clean_query_reports_nothing_flagged(self, tmp_path: Path) -> None:
        source = _write(tmp_path, "q.sql", "SELECT id FROM users WHERE id = 1;")

        result = runner.invoke(app, ["analyze", str(source)])

        assert result.exit_code == 0
        assert "No recommendations" in result.output

    def test_analyze_without_source_exits_validation(self) -> None:
        result = runner.invoke(app, ["analyze"])
        assert result.exit_code == 3


class TestCompareEndToEnd:
    def test_compare_reports_resolved_anti_pattern_and_verdict(
        self, tmp_path: Path
    ) -> None:
        before = _write(tmp_path, "before.sql", "SELECT * FROM users WHERE email = 'a';")
        after = _write(
            tmp_path, "after.sql", "SELECT id, email FROM users WHERE email = 'a';"
        )

        result = runner.invoke(app, ["compare", str(before), str(after)])

        assert result.exit_code == 0
        assert "Anti-patterns:" in result.output
        assert "SELECT_STAR" in result.output
        assert "Verdict: Improvement" in result.output

    def test_compare_missing_sources_exits_validation(self) -> None:
        result = runner.invoke(app, ["compare"])
        assert result.exit_code == 3


class TestPlaceholderAndHelp:
    def test_report_is_still_a_placeholder(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["report", str(tmp_path / "out.json")])
        assert result.exit_code == 0
        assert "not yet implemented" in result.output

    def test_audit_without_db_url_exits_validation(self) -> None:
        result = runner.invoke(app, ["audit"])
        assert result.exit_code == 3

    def test_help_lists_all_commands(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for command in ("analyze", "audit", "report", "compare"):
            assert command in result.output