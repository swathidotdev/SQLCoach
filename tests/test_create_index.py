"""Unit tests for CREATE INDEX generation (US7.4)."""

from __future__ import annotations

import pytest

from sqlcoach.advisor.create_index import generate_create_index, index_name


class TestIndexName:
    def test_single_column(self) -> None:
        assert index_name("users", ("email",)) == "idx_users_email"

    def test_composite(self) -> None:
        assert index_name("orders", ("user_id", "created_at")) == (
            "idx_orders_user_id_created_at"
        )

    def test_truncates_to_postgres_identifier_limit(self) -> None:
        long_col = "c" * 100
        assert len(index_name("t", (long_col,))) == 63


class TestGenerateCreateIndex:
    def test_single_column_statement(self) -> None:
        assert generate_create_index("users", ("email",)) == (
            "CREATE INDEX idx_users_email ON users (email);"
        )

    def test_composite_statement(self) -> None:
        assert generate_create_index("orders", ("user_id", "created_at")) == (
            "CREATE INDEX idx_orders_user_id_created_at ON orders (user_id, created_at);"
        )

    def test_covering_statement_with_include(self) -> None:
        assert generate_create_index(
            "orders", ("user_id",), included_columns=("total", "status")
        ) == (
            "CREATE INDEX idx_orders_user_id ON orders (user_id) INCLUDE (total, status);"
        )

    def test_requires_at_least_one_column(self) -> None:
        with pytest.raises(ValueError):
            generate_create_index("users", ())