"""Unused-index detection (US11.3, FR-4.4).

Flags indexes whose recorded scan count is at or below a threshold
(default zero): they cost write overhead and storage for no read
benefit and are drop candidates.

This is a signal, not proof -- statistics may have been reset, or the
index may serve a rare-but-critical query -- so findings are MEDIUM
confidence with a "verify over a representative period" caveat. As with
duplicates, UNIQUE and PRIMARY KEY indexes are never flagged.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlcoach.advisor.drop_index import generate_drop_index
from sqlcoach.analyzer.base import Severity
from sqlcoach.models.index_catalog import IndexInfo, IndexUsage
from sqlcoach.models.index_hygiene import IndexHygieneFinding
from sqlcoach.models.recommendation import ConfidenceLevel

_CODE = "UNUSED_INDEX"
DEFAULT_MAX_SCANS = 0


class UnusedIndexDetector:
    """Detects indexes with scan counts at or below a threshold."""

    name = "unused_index"

    def __init__(self, max_scans: int = DEFAULT_MAX_SCANS) -> None:
        """Create the detector.

        Args:
            max_scans: An index with this many scans or fewer is flagged.
                Production passes settings.unused_index_max_scans.
        """
        self._max_scans = max_scans

    def detect(
        self, indexes: Sequence[IndexInfo], usage: Sequence[IndexUsage]
    ) -> list[IndexHygieneFinding]:
        usage_by_name = {u.name: u for u in usage}
        findings: list[IndexHygieneFinding] = []
        for index in indexes:
            # A UNIQUE/PK index enforces a constraint even if never scanned.
            if index.is_unique or index.is_primary:
                continue
            usage_row = usage_by_name.get(index.name)
            if usage_row is None:
                continue  # no usage data for this index; can't assess
            if usage_row.scan_count <= self._max_scans:
                findings.append(self._finding(index, usage_row))
        return findings

    def _finding(
        self, index: IndexInfo, usage: IndexUsage
    ) -> IndexHygieneFinding:
        return IndexHygieneFinding(
            code=_CODE,
            detector=self.name,
            severity=Severity.MEDIUM,
            confidence=ConfidenceLevel.MEDIUM,  # a snapshot can't prove truly unused
            summary=(
                f"Index {index.name} on {index.table} has {usage.scan_count} scans "
                f"recorded and appears unused. It still costs write overhead and "
                f"storage. Verify over a representative period before dropping "
                f"(statistics may have been reset), then consider "
                f"DROP INDEX CONCURRENTLY."
            ),
            table=index.table,
            index_name=index.name,
            drop_statement=generate_drop_index(index.name),
            metrics={"scan_count": usage.scan_count},
        )