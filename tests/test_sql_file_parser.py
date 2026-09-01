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


class TestVerbatimTextAndNormalization:
    """`Query.text` must be what the user wrote; `normalized_text` is
    the canonical form used for grouping equivalent queries.
    """

    def test_text_is_preserved_verbatim(
        self, tmp_path: Path, parser: SqlFileParser
    ) -> None:
        sql_file = tmp_path / "q.sql"
        sql_file.write_text(
            "SELECT o.id, o.total\n"
            "FROM orders o\n"
            "WHERE o.created_at > NOW() - INTERVAL '7 days';\n"
        )

        results = parser.parse(sql_file)

        assert results[0].text == (
            "SELECT o.id, o.total\n"
            "FROM orders o\n"
            "WHERE o.created_at > NOW() - INTERVAL '7 days'"
        )

    def test_normalized_text_is_populated_and_canonical(
        self, tmp_path: Path, parser: SqlFileParser
    ) -> None:
        sql_file = tmp_path / "q.sql"
        sql_file.write_text("select   *   from    users   where id = 1;")

        results = parser.parse(sql_file)

        normalized = results[0].normalized_text
        assert normalized is not None
        assert normalized == "SELECT * FROM users WHERE id = 1"

    def test_equivalent_queries_share_a_fingerprint(
        self, tmp_path: Path, parser: SqlFileParser
    ) -> None:
        sql_file = tmp_path / "q.sql"
        sql_file.write_text(
            "SELECT id FROM users WHERE id = 1;\n"
            "select   id\nfrom users\nwhere id = 1;\n"
        )

        results = parser.parse(sql_file)

        assert len(results) == 2
        assert results[0].text != results[1].text
        assert results[0].fingerprint == results[1].fingerprint


class TestStatementLineNumbers:
    def test_every_statement_reports_its_own_starting_line(
        self, tmp_path: Path, parser: SqlFileParser
    ) -> None:
        sql_file = tmp_path / "q.sql"
        sql_file.write_text(
            "-- header comment\n"
            "SELECT 1;\n"
            "\n"
            "SELECT 2;\n"
            "\n"
            "\n"
            "SELECT 3;\n"
        )

        results = parser.parse(sql_file)

        assert [r.source_location for r in results] == [
            f"{sql_file}:line 1",
            f"{sql_file}:line 4",
            f"{sql_file}:line 7",
        ]

    def test_dollar_quoted_body_does_not_shift_later_line_numbers(
        self, tmp_path: Path, parser: SqlFileParser
    ) -> None:
        sql_file = tmp_path / "q.sql"
        sql_file.write_text(
            "CREATE FUNCTION f() RETURNS int AS $$\n"
            "BEGIN\n"
            "  RETURN 1;\n"
            "END;\n"
            "$$ LANGUAGE plpgsql;\n"
            "SELECT * FROM users;\n"
        )

        results = parser.parse(sql_file)

        assert len(results) == 2
        assert results[1].statement_type == "SELECT"
        assert results[1].source_location == f"{sql_file}:line 6"