"""Index advisor (Sprint 7).

Turns analyzer findings plus query structure into `IndexRecommendation`
objects. The advisor is *finding-driven*: it proposes an index only for
a table that the plan analyzer flagged with a large sequential scan
(`SEQ_SCAN_LARGE_TABLE`). That finding is the evidence the table's
access path is both slow and unindexed -- had a usable index existed,
PostgreSQL would have chosen an index scan and produced no such
finding. This gives high precision and, for free, avoids recommending
indexes on small tables (never flagged) or ones already served by a
usable index (would appear as an index scan, not a seq scan).

The finding supplies *which table*; the query's parsed columns supply
*which columns* to index. Single-column (US7.1), composite (US7.2), and
covering (US7.3) indexes are all produced here.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence

from sqlcoach.advisor.column_usage import ColumnUsage, extract_column_usage
from sqlcoach.advisor.create_index import generate_create_index
from sqlcoach.analyzer.base import Finding, Severity
from sqlcoach.models.index_recommendation import IndexKind, IndexRecommendation
from sqlcoach.models.recommendation import ConfidenceLevel

logger = logging.getLogger(__name__)

# Must match the code emitted by
# sqlcoach.analyzer.detectors.seq_scan.SequentialScanDetector. The
# advisor test feeds a real detector finding through to guard against
# this drifting.
_SEQ_SCAN_FINDING_CODE = "SEQ_SCAN_LARGE_TABLE"

# Constructor default; production wires
# settings.covering_index_max_included_columns through instead.
_DEFAULT_MAX_INCLUDED_COLUMNS = 3

_CONFIDENCE_RANK = {
    ConfidenceLevel.LOW: 0,
    ConfidenceLevel.MEDIUM: 1,
    ConfidenceLevel.HIGH: 2,
}


def _confidence_from(severity: Severity) -> ConfidenceLevel:
    """Map a finding's severity to a recommendation confidence.

    A seq scan confirmed by measured (actual) rows is HIGH severity and
    yields HIGH confidence; an estimate-only scan is the softer signal.
    """
    return ConfidenceLevel.HIGH if severity is Severity.HIGH else ConfidenceLevel.MEDIUM


def _index_key_columns(usage: ColumnUsage) -> list[str]:
    """Compute the ordered key columns for an index serving this table.

    Column order follows the PostgreSQL composite-index rule, which is
    what makes a b-tree index actually usable for a multi-predicate
    query:

    1. **Equality and join columns first.** A b-tree can apply equality
       predicates on any run of leading columns, and a join key acts
       like an equality against the other side's value.
    2. **Then a single range column.** A range predicate (``>``, ``<``,
       BETWEEN) can use the index, but it "stops" the index from using
       any later column for further filtering or ordering -- so only the
       first range column earns a place in the key.
    3. **Then ORDER BY columns, but only when there is no range column.**
       With an equality-led prefix and no range break, trailing ORDER BY
       columns let the index supply sorted output and skip a sort. A
       range predicate defeats this, so ORDER BY columns are dropped
       when a range column is present.

    ORDER BY columns are only appended when there is an equality/join
    leading column; a bare ``ORDER BY`` with no filter is left for a
    later refinement rather than recommending an index solely to avoid
    a sort.

    Column order *within* the equality tier is by first appearance.
    Optimal ordering can depend on per-column selectivity, which isn't
    known statically -- a documented simplification.
    """
    key: list[str] = []

    def add(column: str) -> None:
        if column not in key:
            key.append(column)

    for column in usage.equality_filters:
        add(column)
    for column in usage.join_columns:
        add(column)

    has_leading = bool(key)

    if usage.range_filters:
        for column in usage.range_filters:
            if column not in key:
                add(column)
                break  # a range column terminates the useful key
    elif has_leading:
        for column in usage.order_by_columns:
            add(column)

    return key


def _covering_columns(
    usage: ColumnUsage, key: Sequence[str], max_included: int
) -> tuple[str, ...]:
    """Return the INCLUDE columns for a covering index, or () if none.

    Covering does not apply -- and this returns () -- when:
    - the query selects ``*`` (unknown columns), or
    - covering is disabled (`max_included` <= 0), or
    - every selected column is already a key column (already index-only
      capable), or
    - there are more extra columns than `max_included` (an oversized
      INCLUDE costs more in write overhead and storage than the
      index-only scan is worth).
    """
    if usage.select_is_star or max_included <= 0:
        return ()
    key_set = set(key)
    extra = [column for column in usage.selected_columns if column not in key_set]
    if not extra or len(extra) > max_included:
        return ()
    return tuple(extra)


class IndexAdvisor:
    """Produces index recommendations from findings and query structure."""

    def __init__(self, max_included_columns: int = _DEFAULT_MAX_INCLUDED_COLUMNS) -> None:
        """Create an advisor.

        Args:
            max_included_columns: The largest INCLUDE list a covering
                index may carry. 0 disables covering entirely. Production
                passes settings.covering_index_max_included_columns.
        """
        self._max_included = max_included_columns

    def recommend_for_query(
        self, sql: str, findings: Sequence[Finding]
    ) -> list[IndexRecommendation]:
        """Recommend indexes for one query.

        Args:
            sql: The query's SQL text, used to extract filter/join/sort
                and selected columns.
            findings: The analyzer findings for this query.

        Returns:
            Zero or more IndexRecommendations, one per seq-scanned table
            that has at least one indexable column. A single indexable
            column yields a single-column index; two or more yield a
            composite; either becomes a covering index when the query's
            selected columns can be economically included.
        """
        usage_by_table = extract_column_usage(sql)
        recommendations: list[IndexRecommendation] = []

        for finding in findings:
            if finding.code != _SEQ_SCAN_FINDING_CODE:
                continue
            table = finding.relation_name
            if table is None:
                continue
            usage = usage_by_table.get(table)
            if usage is None:
                # A seq scan was flagged but the query has no attributable
                # predicate on that table (e.g. an unfiltered full scan, or
                # only ambiguous unqualified columns). An index wouldn't
                # help an unfiltered scan, so there's nothing to recommend.
                continue

            key_columns = _index_key_columns(usage)
            if not key_columns:
                continue

            included = _covering_columns(usage, key_columns, self._max_included)
            recommendations.append(
                self._build(table, tuple(key_columns), included, finding)
            )

        return recommendations

    def recommend_for_workload(
        self, queries: Iterable[tuple[str, Sequence[Finding]]]
    ) -> list[IndexRecommendation]:
        """Deduplicate recommendations across many (sql, findings) pairs.

        Identical indexes -- same table, key columns, and INCLUDE columns
        -- collapse to one, keeping the highest confidence seen. First-seen
        order is preserved for determinism. Frequency-based *ranking* is
        left to the recommendation engine (Sprint 9), which owns
        prioritization across all recommendation sources; merging here
        only removes exact duplicates.
        """
        merged: dict[tuple[str, tuple[str, ...], tuple[str, ...]], IndexRecommendation] = {}
        for sql, findings in queries:
            for rec in self.recommend_for_query(sql, findings):
                identity = (rec.table, rec.columns, rec.included_columns)
                existing = merged.get(identity)
                if existing is None:
                    merged[identity] = rec
                elif _CONFIDENCE_RANK[rec.confidence] > _CONFIDENCE_RANK[existing.confidence]:
                    merged[identity] = existing.model_copy(
                        update={"confidence": rec.confidence}
                    )
        return list(merged.values())

    def _build(
        self,
        table: str,
        columns: tuple[str, ...],
        included: tuple[str, ...],
        finding: Finding,
    ) -> IndexRecommendation:
        is_covering = bool(included)
        is_composite = len(columns) > 1

        if is_covering:
            kind = IndexKind.COVERING
            rationale = (
                f"A large sequential scan on {table} filters on "
                f"({', '.join(columns)}) and returns only ({', '.join(included)}); a "
                f"covering index enables an index-only scan, avoiding heap fetches."
            )
        elif is_composite:
            kind = IndexKind.COMPOSITE
            rationale = (
                f"A large sequential scan on {table} filters, joins, or sorts on "
                f"multiple columns; a composite index on ({', '.join(columns)}) "
                f"covers the combined access pattern (equality and join columns "
                f"first, then a range or sort column)."
            )
        else:
            kind = IndexKind.SINGLE_COLUMN
            rationale = (
                f"A large sequential scan on {table} filters or joins on "
                f"{columns[0]}, which has no usable index."
            )

        return IndexRecommendation(
            table=table,
            columns=columns,
            included_columns=included,
            kind=kind,
            create_statement=generate_create_index(table, columns, included),
            rationale=rationale,
            confidence=_confidence_from(finding.severity),
            source_finding_code=finding.code,
        )