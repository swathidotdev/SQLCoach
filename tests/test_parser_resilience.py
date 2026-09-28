"""Coverage for parser resilience fallbacks (Sprint 12)."""

from __future__ import annotations

from pathlib import Path

from sqlcoach.parser.log_parser import LogParser
from sqlcoach.parser.sql_file_parser import SqlFileParser


class TestSqlFileParserFallback:
    def test_untokenizable_input_falls_back_to_naive_split(self, tmp_path: Path) -> None:
        # An unterminated dollar-quoted body makes the whole file
        # untokenizable, forcing the naive-split fallback path. The one
        # valid statement should still be recovered.
        sql_file = tmp_path / "broken.sql"
        sql_file.write_text(
            "SELECT id FROM users WHERE id = 1;\n"
            "CREATE FUNCTION f() RETURNS int AS $$ unterminated body\n"
        )

        queries = SqlFileParser().parse(sql_file)

        # The valid SELECT is recovered even though the file can't be
        # tokenized cleanly; the parser doesn't raise.
        assert any(q.statement_type == "SELECT" for q in queries)

    def test_empty_file_yields_no_queries(self, tmp_path: Path) -> None:
        sql_file = tmp_path / "empty.sql"
        sql_file.write_text("   \n  \n")
        assert SqlFileParser().parse(sql_file) == []


class TestLogParserResilience:
    def test_malformed_duration_is_skipped_not_fatal(self, tmp_path: Path) -> None:
        log_file = tmp_path / "pg.log"
        # A duration that isn't a number: the entry is skipped, not fatal.
        log_file.write_text(
            "2024-01-15 10:00:00.000 UTC [1] LOG:  duration: NOTANUMBER ms  "
            "statement: SELECT 1;\n"
            "2024-01-15 10:00:01.000 UTC [1] LOG:  duration: 12.5 ms  "
            "statement: SELECT 2;\n"
        )

        queries = LogParser().parse(log_file)

        # The good entry is parsed; the malformed one is dropped.
        assert len(queries) == 1
        assert queries[0].execution_time_ms == 12.5