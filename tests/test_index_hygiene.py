"""Unit tests for index-hygiene detection: duplicate + unused indexes (Sprint 11)."""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlcoach.advisor.drop_index import generate_drop_index
from sqlcoach.advisor.duplicate_index_detector import DuplicateIndexDetector
from sqlcoach.advisor.unused_index_detector import UnusedIndexDetector
from sqlcoach.database.index_catalog import fetch_index_usage, fetch_indexes
from sqlcoach.models.index_catalog import IndexInfo, IndexUsage
from sqlcoach.models.recommendation import ConfidenceLevel


def _index(
    name: str,
    table: str,
    columns: tuple[str, ...],
    *,
    unique: bool = False,
    primary: bool = False,
) -> IndexInfo:
    return IndexInfo(
        name=name, table=table, columns=columns, is_unique=unique, is_primary=primary
    )


class TestDuplicateIndex:
    def test_prefix_redundant_index_is_flagged(self) -> None:
        findings = DuplicateIndexDetector().detect(
            [_index("idx_a", "t", ("a",)), _index("idx_ab", "t", ("a", "b"))]
        )
        assert [f.index_name for f in findings] == ["idx_a"]
        assert findings[0].code == "DUPLICATE_INDEX"
        assert findings[0].confidence is ConfidenceLevel.HIGH
        assert findings[0].drop_statement == "DROP INDEX idx_a;"

    def test_exact_duplicate_flags_one_deterministically(self) -> None:
        findings = DuplicateIndexDetector().detect(
            [_index("idx_x2", "t", ("a",)), _index("idx_x1", "t", ("a",))]
        )
        # idx_x1 kept (name sorts first); idx_x2 flagged.
        assert [f.index_name for f in findings] == ["idx_x2"]

    def test_primary_key_is_never_flagged(self) -> None:
        findings = DuplicateIndexDetector().detect(
            [_index("pk", "t", ("id",), primary=True), _index("idx_id_x", "t", ("id", "x"))]
        )
        assert findings == []

    def test_plain_duplicate_of_unique_is_flagged_unique_kept(self) -> None:
        findings = DuplicateIndexDetector().detect(
            [_index("uq", "t", ("email",), unique=True), _index("idx_email", "t", ("email",))]
        )
        assert [f.index_name for f in findings] == ["idx_email"]

    def test_distinct_columns_not_flagged(self) -> None:
        assert (
            DuplicateIndexDetector().detect(
                [_index("idx_a", "t", ("a",)), _index("idx_b", "t", ("b",))]
            )
            == []
        )

    def test_same_columns_different_tables_not_flagged(self) -> None:
        assert (
            DuplicateIndexDetector().detect(
                [_index("i1", "t1", ("a",)), _index("i2", "t2", ("a",))]
            )
            == []
        )


class TestUnusedIndex:
    def test_zero_scan_index_flagged_medium_confidence(self) -> None:
        indexes = [
            _index("idx_used", "t", ("a",)),
            _index("idx_unused", "t", ("b",)),
            _index("pk", "t", ("id",), primary=True),
        ]
        usage = [
            IndexUsage(name="idx_used", table="t", scan_count=5000),
            IndexUsage(name="idx_unused", table="t", scan_count=0),
            IndexUsage(name="pk", table="t", scan_count=0),
        ]

        findings = UnusedIndexDetector().detect(indexes, usage)

        assert [f.index_name for f in findings] == ["idx_unused"]  # used + pk excluded
        assert findings[0].confidence is ConfidenceLevel.MEDIUM
        assert findings[0].metrics["scan_count"] == 0

    def test_threshold_is_configurable(self) -> None:
        findings = UnusedIndexDetector(max_scans=10).detect(
            [_index("idx_low", "t", ("a",))],
            [IndexUsage(name="idx_low", table="t", scan_count=7)],
        )
        assert [f.index_name for f in findings] == ["idx_low"]

    def test_index_without_usage_row_is_skipped(self) -> None:
        assert UnusedIndexDetector().detect([_index("idx_x", "t", ("a",))], []) == []

    def test_unique_never_flagged_even_if_unused(self) -> None:
        findings = UnusedIndexDetector().detect(
            [_index("uq", "t", ("email",), unique=True)],
            [IndexUsage(name="uq", table="t", scan_count=0)],
        )
        assert findings == []


class TestDropIndexGeneration:
    def test_drop_statement(self) -> None:
        assert generate_drop_index("idx_users_email") == "DROP INDEX idx_users_email;"


class TestCatalogReaders:
    def test_fetch_indexes_groups_ordered_columns(self) -> None:
        connection = MagicMock()
        cursor = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        # Flat rows: (index_name, table, is_unique, is_primary, attname, ord)
        cursor.fetchall.return_value = [
            ("idx_ab", "orders", False, False, "a", 1),
            ("idx_ab", "orders", False, False, "b", 2),
            ("pk_users", "users", True, True, "id", 1),
        ]

        indexes = {i.name: i for i in fetch_indexes(connection)}

        assert indexes["idx_ab"].columns == ("a", "b")
        assert indexes["pk_users"].is_primary is True

    def test_fetch_index_usage_maps_rows_and_coerces_null(self) -> None:
        connection = MagicMock()
        cursor = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchall.return_value = [("idx_a", "t", 42), ("idx_b", "t", None)]

        usage = {u.name: u.scan_count for u in fetch_index_usage(connection)}

        assert usage["idx_a"] == 42
        assert usage["idx_b"] == 0  # NULL coerced to 0