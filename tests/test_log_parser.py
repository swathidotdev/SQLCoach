"""Unit tests for sqlcoach.parser.log_parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from sqlcoach.models.query import QuerySource
from sqlcoach.parser.log_parser import LogParser


@pytest.fixture
def parser() -> LogParser:
    return LogParser()


class TestSimpleBlockFormat:
    def test_parses_a_single_block(self, tmp_path: Path, parser: LogParser) -> None:
        log_file = tmp_path / "postgres.log"
        log_file.write_text(
            "Query:\n"
            "SELECT * FROM orders WHERE user_id = 10;\n"
            "\n"
            "Execution Time:\n"
            "820 ms\n"
        )

        results = parser.parse(log_file)

        assert len(results) == 1
        query = results[0]
        assert query.source is QuerySource.LOG_FILE
        assert query.text == "SELECT * FROM orders WHERE user_id = 10;"
        assert query.execution_time_ms == 820.0
        assert query.statement_type == "SELECT"
        assert query.referenced_tables == ("orders",)

    def test_parses_multiple_blocks(self, tmp_path: Path, parser: LogParser) -> None:
        log_file = tmp_path / "postgres.log"
        log_file.write_text(
            "Query:\n"
            "SELECT 1;\n"
            "\n"
            "Execution Time:\n"
            "5 ms\n"
            "\n"
            "Query:\n"
            "SELECT 2;\n"
            "\n"
            "Execution Time:\n"
            "10.5 ms\n"
        )

        results = parser.parse(log_file)

        assert len(results) == 2
        assert results[0].execution_time_ms == 5.0
        assert results[1].execution_time_ms == 10.5


class TestDurationLogFormat:
    def test_parses_a_single_line_entry(self, tmp_path: Path, parser: LogParser) -> None:
        log_file = tmp_path / "postgres.log"
        log_file.write_text(
            "2024-01-15 10:23:45.123 UTC [12345] LOG:  duration: 820.123 ms  "
            "statement: SELECT * FROM orders WHERE user_id = 10;\n"
        )

        results = parser.parse(log_file)

        assert len(results) == 1
        query = results[0]
        assert query.source is QuerySource.LOG_FILE
        assert query.execution_time_ms == 820.123
        assert query.text == "SELECT * FROM orders WHERE user_id = 10;"
        assert query.statement_type == "SELECT"
        assert query.referenced_tables == ("orders",)

    def test_parses_multiple_entries(self, tmp_path: Path, parser: LogParser) -> None:
        log_file = tmp_path / "postgres.log"
        log_file.write_text(
            "2024-01-15 10:23:45.123 UTC [12345] LOG:  duration: 820.123 ms  "
            "statement: SELECT * FROM orders;\n"
            "2024-01-15 10:24:01.456 UTC [12346] LOG:  duration: 15.002 ms  "
            "statement: SELECT * FROM users;\n"
        )

        results = parser.parse(log_file)

        assert len(results) == 2
        assert results[0].execution_time_ms == 820.123
        assert results[1].execution_time_ms == 15.002

    def test_handles_multiline_statement(self, tmp_path: Path, parser: LogParser) -> None:
        log_file = tmp_path / "postgres.log"
        log_file.write_text(
            "2024-01-15 10:24:05.789 UTC [12347] LOG:  duration: 42.100 ms  "
            "statement: SELECT *\n"
            "\tFROM big_table\n"
            "\tWHERE x = 1;\n"
        )

        results = parser.parse(log_file)

        assert len(results) == 1
        assert "big_table" in results[0].text
        assert results[0].referenced_tables == ("big_table",)

    def test_stops_continuation_at_next_timestamped_entry(
        self, tmp_path: Path, parser: LogParser
    ) -> None:
        log_file = tmp_path / "postgres.log"
        log_file.write_text(
            "2024-01-15 10:23:45.123 UTC [12345] LOG:  duration: 1.0 ms  "
            "statement: SELECT 1;\n"
            "2024-01-15 10:23:46.000 UTC [12345] LOG:  duration: 2.0 ms  "
            "statement: SELECT 2;\n"
        )

        results = parser.parse(log_file)

        assert len(results) == 2
        assert results[0].text == "SELECT 1;"
        assert results[1].text == "SELECT 2;"


class TestNoRecognizedFormat:
    def test_unrecognized_content_returns_empty_list(
        self, tmp_path: Path, parser: LogParser
    ) -> None:
        log_file = tmp_path / "not_a_log.txt"
        log_file.write_text("This is just some random text file.\nNothing to see here.\n")

        assert parser.parse(log_file) == []

    def test_empty_file_returns_empty_list(self, tmp_path: Path, parser: LogParser) -> None:
        log_file = tmp_path / "empty.log"
        log_file.write_text("")

        assert parser.parse(log_file) == []


class TestMalformedExecutionTime:
    def test_skips_block_with_unparseable_execution_time(
        self, tmp_path: Path, parser: LogParser, caplog: pytest.LogCaptureFixture
    ) -> None:
        log_file = tmp_path / "postgres.log"
        # "12.34.56" matches the [\d.]+ pattern (digits and dots) but is
        # not a valid float -- this is what actually exercises the
        # ValueError path, unlike purely non-numeric text like
        # "not-a-number" which simply wouldn't match the regex at all.
        log_file.write_text(
            "Query:\n"
            "SELECT 1;\n"
            "\n"
            "Execution Time:\n"
            "12.34.56 ms\n"
        )

        with caplog.at_level("WARNING"):
            results = parser.parse(log_file)

        assert results == []
        assert any("Skipping log block" in message for message in caplog.messages)