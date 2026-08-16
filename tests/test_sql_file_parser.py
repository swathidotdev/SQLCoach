"""Unit tests for sqlcoach.parser.sql_file_parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from sqlcoach.models.query import QuerySource
from sqlcoach.parser.sql_file_parser import SqlFileParser


@pytest.fixture
def parser() -> SqlFileParser:
    return SqlFileParser()


class TestBasicParsing:
    def test_parses_a_single_statement_file(
        self, tmp_path: Path, parser: SqlFileParser
    ) -> None:
        sql_file = tmp_path / "queries.sql"
        sql_file.write_text("SELECT * FROM users WHERE id = 1;")

        results = parser.parse(sql_file)

        assert len(results) == 1
        assert results[0].source is QuerySource.SQL_FILE
        assert results[0].statement_type == "SELECT"
        assert results[0].referenced_tables == ("users",)

    def test_parses_multiple_statements(
        self, tmp_path: Path, parser: SqlFileParser
    ) -> None:
        sql_file = tmp_path / "queries.sql"
        sql_file.write_text(
            "SELECT * FROM users;\n"
            "INSERT INTO orders (id) VALUES (1);\n"
            "UPDATE users SET name = 'x' WHERE id = 1;\n"
        )

        results = parser.parse(sql_file)

        assert len(results) == 3
        assert [r.statement_type for r in results] == ["SELECT", "INSERT", "UPDATE"]

    def test_empty_file_returns_no_queries(
        self, tmp_path: Path, parser: SqlFileParser
    ) -> None:
        sql_file = tmp_path / "empty.sql"
        sql_file.write_text("")

        assert parser.parse(sql_file) == []

    def test_comment_only_file_returns_no_queries(
        self, tmp_path: Path, parser: SqlFileParser
    ) -> None:
        sql_file = tmp_path / "comments.sql"
        sql_file.write_text("-- just a comment\n")

        assert parser.parse(sql_file) == []


class TestTableExtraction:
    def test_extracts_single_table(self, tmp_path: Path, parser: SqlFileParser) -> None:
        sql_file = tmp_path / "q.sql"
        sql_file.write_text("SELECT * FROM orders WHERE user_id = 10;")

        results = parser.parse(sql_file)

        assert results[0].referenced_tables == ("orders",)

    def test_extracts_multiple_tables_from_a_join(
        self, tmp_path: Path, parser: SqlFileParser
    ) -> None:
        sql_file = tmp_path / "q.sql"
        sql_file.write_text("SELECT * FROM orders JOIN users ON orders.user_id = users.id;")

        results = parser.parse(sql_file)

        assert set(results[0].referenced_tables) == {"orders", "users"}

    def test_query_with_no_table_has_empty_tuple(
        self, tmp_path: Path, parser: SqlFileParser
    ) -> None:
        sql_file = tmp_path / "q.sql"
        sql_file.write_text("SELECT 1;")

        results = parser.parse(sql_file)

        assert results[0].referenced_tables == ()


class TestDollarQuotingAndStringLiterals:
    def test_semicolon_inside_string_literal_does_not_split_statement(
        self, tmp_path: Path, parser: SqlFileParser
    ) -> None:
        sql_file = tmp_path / "q.sql"
        sql_file.write_text("SELECT * FROM logs WHERE message = 'a;b;c';")

        results = parser.parse(sql_file)

        assert len(results) == 1

    def test_dollar_quoted_function_body_stays_one_statement(
        self, tmp_path: Path, parser: SqlFileParser
    ) -> None:
        sql_file = tmp_path / "q.sql"
        sql_file.write_text(
            "CREATE FUNCTION f() RETURNS void AS $$ BEGIN SELECT 1; END; $$ "
            "LANGUAGE plpgsql;\n"
            "DELETE FROM logs WHERE id = 3;\n"
        )

        results = parser.parse(sql_file)

        assert len(results) == 2
        assert results[0].statement_type == "CREATE"
        assert results[1].statement_type == "DELETE"


class TestResilientErrorHandling:
    def test_skips_malformed_statement_and_keeps_the_rest(
        self, tmp_path: Path, parser: SqlFileParser, caplog: pytest.LogCaptureFixture
    ) -> None:
        sql_file = tmp_path / "q.sql"
        sql_file.write_text(
            "SELECT * FROM users;\n"
            "SELEC * FRM broken syntax here;\n"
            "UPDATE users SET name = 'x' WHERE id = 2;\n"
        )

        with caplog.at_level("WARNING"):
            results = parser.parse(sql_file)

        assert len(results) == 2
        assert [r.statement_type for r in results] == ["SELECT", "UPDATE"]
        assert any("Skipping unparseable statement" in message for message in caplog.messages)

    def test_skipped_statement_warning_includes_line_number_and_snippet(
        self, tmp_path: Path, parser: SqlFileParser, caplog: pytest.LogCaptureFixture
    ) -> None:
        sql_file = tmp_path / "q.sql"
        sql_file.write_text("SELECT * FROM users;\nSELEC * FRM broken syntax here;\n")

        with caplog.at_level("WARNING"):
            parser.parse(sql_file)

        warning_messages = [m for m in caplog.messages if "Skipping unparseable" in m]
        assert len(warning_messages) == 1
        assert "line 2" in warning_messages[0]
        assert "SELEC" in warning_messages[0]

    def test_does_not_raise_on_thoroughly_malformed_input(
        self, tmp_path: Path, parser: SqlFileParser
    ) -> None:
        sql_file = tmp_path / "q.sql"
        sql_file.write_text("TOTALLY NOT ; VALID *** SQL ###;")

        # The important guarantee is that this never raises out of parse();
        # exactly what gets kept vs skipped depends on sqlglot's lenient
        # grammar and isn't asserted here.
        results = parser.parse(sql_file)
        assert isinstance(results, list)