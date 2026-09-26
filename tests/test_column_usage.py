"""Unit tests for advisor column-usage extraction."""

from __future__ import annotations

from sqlcoach.advisor.column_usage import extract_column_usage


class TestSingleTable:
    def test_equality_filter_unqualified(self) -> None:
        usage = extract_column_usage("SELECT id FROM users WHERE email = 'a@b.com'")
        assert usage["users"].equality_filters == ("email",)

    def test_range_filter_and_between(self) -> None:
        usage = extract_column_usage(
            "SELECT id FROM orders WHERE amount > 100 AND status BETWEEN 1 AND 3"
        )
        assert usage["orders"].range_filters == ("amount", "status")

    def test_order_by_and_selected(self) -> None:
        usage = extract_column_usage(
            "SELECT id, total FROM orders WHERE user_id = 5 ORDER BY created_at DESC"
        )
        o = usage["orders"]
        assert o.equality_filters == ("user_id",)
        assert o.order_by_columns == ("created_at",)
        assert o.selected_columns == ("id", "total")
        assert o.select_is_star is False

    def test_select_star_is_flagged(self) -> None:
        usage = extract_column_usage("SELECT * FROM users WHERE email = 'x'")
        assert usage["users"].select_is_star is True


class TestMultiTable:
    def test_join_columns_and_alias_resolution(self) -> None:
        usage = extract_column_usage(
            "SELECT o.id FROM orders o JOIN users u ON u.id = o.user_id "
            "WHERE o.status = 1"
        )
        assert "user_id" in usage["orders"].join_columns
        assert usage["orders"].equality_filters == ("status",)
        assert usage["users"].join_columns == ("id",)

    def test_unqualified_column_is_skipped_when_ambiguous(self) -> None:
        # `status` has no table qualifier in a two-table query, so it
        # cannot be safely attributed and is dropped.
        usage = extract_column_usage(
            "SELECT id FROM orders o JOIN users u ON u.id = o.user_id WHERE status = 1"
        )
        assert usage["orders"].equality_filters == ()
        assert usage["users"].equality_filters == ()

    def test_qualified_star_marks_only_that_table(self) -> None:
        usage = extract_column_usage(
            "SELECT o.* FROM orders o JOIN users u ON u.id = o.user_id"
        )
        assert usage["orders"].select_is_star is True
        assert usage["users"].select_is_star is False


class TestResilience:
    def test_unparseable_sql_returns_empty(self) -> None:
        assert extract_column_usage("SELCT broken !!") == {}

    def test_column_used_as_both_filter_and_join(self) -> None:
        usage = extract_column_usage(
            "SELECT o.id FROM orders o JOIN users u ON u.id = o.user_id "
            "WHERE o.user_id = 20"
        )
        # user_id appears as both an equality filter and a join key.
        assert usage["orders"].equality_filters == ("user_id",)
        assert "user_id" in usage["orders"].join_columns



class TestStarDetection:
    def test_count_star_is_not_a_select_star(self) -> None:
        # A star nested inside COUNT(*) must not flag select_is_star,
        # or covering-index analysis would be wrongly suppressed.
        usage = extract_column_usage("SELECT COUNT(*) FROM orders WHERE user_id = 20")
        assert usage["orders"].select_is_star is False
        assert usage["orders"].selected_columns == ()

    def test_bare_star_is_flagged(self) -> None:
        usage = extract_column_usage("SELECT * FROM users WHERE email = 'x'")
        assert usage["users"].select_is_star is True

    def test_aggregate_over_a_column_selects_that_column(self) -> None:
        # max(amount) selects `amount`; no star involved.
        usage = extract_column_usage("SELECT max(amount) FROM orders WHERE user_id = 20")
        assert usage["orders"].select_is_star is False
        assert "amount" in usage["orders"].selected_columns