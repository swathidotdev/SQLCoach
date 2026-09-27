"""Duplicate-index detection (US11.2, FR-4.3).

Flags an index that is redundant because another index on the same table
already covers it -- either an exact duplicate, or a leading-prefix
subset (``(a)`` is redundant when ``(a, b)`` exists, since the composite
serves ``(a)`` lookups too). Prefix redundancy catches far more real
waste than exact-duplicate matching alone.

Safety rule: a UNIQUE or PRIMARY KEY index is never recommended for
dropping, even when redundant -- it enforces a constraint, not just
speed. And for an exact-duplicate pair, exactly one is flagged (the
other is kept), chosen deterministically.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlcoach.advisor.drop_index import generate_drop_index
from sqlcoach.analyzer.base import Severity
from sqlcoach.models.index_catalog import IndexInfo
from sqlcoach.models.index_hygiene import IndexHygieneFinding
from sqlcoach.models.recommendation import ConfidenceLevel

_CODE = "DUPLICATE_INDEX"


def _is_proper_prefix(short: tuple[str, ...], long: tuple[str, ...]) -> bool:
    return len(short) < len(long) and long[: len(short)] == short


def _keep_over(keep: IndexInfo, drop: IndexInfo) -> bool:
    """True if `keep` is the index to retain when it duplicates `drop`."""
    # A constraint-backing index is always the one kept.
    if keep.is_unique or keep.is_primary:
        return True
    # Deterministic tiebreak between two equivalent non-constraint indexes.
    return keep.name < drop.name


class DuplicateIndexDetector:
    """Detects redundant indexes covered by another index on the same table."""

    name = "duplicate_index"

    def detect(self, indexes: Sequence[IndexInfo]) -> list[IndexHygieneFinding]:
        by_table: dict[str, list[IndexInfo]] = {}
        for index in indexes:
            by_table.setdefault(index.table, []).append(index)

        findings: list[IndexHygieneFinding] = []
        for table_indexes in by_table.values():
            for candidate in table_indexes:
                # Never recommend dropping a constraint-backing index.
                if candidate.is_unique or candidate.is_primary:
                    continue
                covering = self._find_covering(candidate, table_indexes)
                if covering is not None:
                    findings.append(self._finding(candidate, covering))
        return findings

    @staticmethod
    def _find_covering(
        candidate: IndexInfo, table_indexes: Sequence[IndexInfo]
    ) -> IndexInfo | None:
        for other in table_indexes:
            if other is candidate:
                continue
            if candidate.columns == other.columns:
                # Exact duplicate: flag `candidate` only if `other` is kept.
                if _keep_over(other, candidate):
                    return other
            elif _is_proper_prefix(candidate.columns, other.columns):
                # `candidate` is a leading-prefix subset of composite `other`.
                return other
        return None

    def _finding(
        self, redundant: IndexInfo, covering: IndexInfo
    ) -> IndexHygieneFinding:
        columns = ", ".join(redundant.columns)
        covering_columns = ", ".join(covering.columns)
        return IndexHygieneFinding(
            code=_CODE,
            detector=self.name,
            severity=Severity.MEDIUM,
            confidence=ConfidenceLevel.HIGH,  # redundancy is provable from the catalog
            summary=(
                f"Index {redundant.name} on {redundant.table} ({columns}) is redundant: "
                f"index {covering.name} ({covering_columns}) already covers it. Dropping "
                f"it reclaims write overhead and storage. Verify, then consider "
                f"DROP INDEX CONCURRENTLY to avoid locking."
            ),
            table=redundant.table,
            index_name=redundant.name,
            drop_statement=generate_drop_index(redundant.name),
            metrics={"covered_by_indexes": 1},
        )