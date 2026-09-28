"""PostgreSQL index catalog readers (Sprint 11).

Reads index definitions and usage statistics from the system catalogs
for the audit command's index-hygiene checks. Read-only (NFR-4.2), and
tested with mocked cursors -- the real catalog queries are exercised
against a live database in Phase 5.
"""

from __future__ import annotations

import logging

import psycopg

from sqlcoach.exceptions import DatabaseConnectionError
from sqlcoach.models.index_catalog import IndexInfo, IndexUsage

logger = logging.getLogger(__name__)

# One row per (index, key-column position). Ordered so a query's columns
# arrive in index order; grouped into IndexInfo in Python. Expression
# index columns come back with a NULL attname.
_INDEXES_SQL = """
SELECT ix.relname AS index_name, t.relname AS table_name,
       i.indisunique, i.indisprimary, a.attname, k.ord
FROM pg_index i
JOIN pg_class t ON t.oid = i.indrelid
JOIN pg_class ix ON ix.oid = i.indexrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord) ON true
LEFT JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY table_name, index_name, k.ord
"""

_USAGE_SQL = """
SELECT indexrelname AS index_name, relname AS table_name, idx_scan
FROM pg_stat_user_indexes
"""


def fetch_indexes(connection: psycopg.Connection) -> list[IndexInfo]:
    """Read all user indexes with their ordered key columns.

    Raises:
        DatabaseConnectionError: If the catalog query fails.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(_INDEXES_SQL)
            rows = cursor.fetchall()
    except psycopg.Error as exc:
        raise DatabaseConnectionError(
            "Could not read index catalog", details={"reason": str(exc)}
        ) from exc

    grouped: dict[str, dict] = {}
    for index_name, table_name, is_unique, is_primary, attname, _ord in rows:
        entry = grouped.setdefault(
            index_name,
            {
                "table": table_name,
                "is_unique": is_unique,
                "is_primary": is_primary,
                "columns": [],
            },
        )
        # NULL attname == an expression-index column; keep it as a
        # placeholder so column counts stay correct (it won't compare
        # equal to a plain column, so such indexes simply won't be
        # matched as duplicates -- the safe outcome).
        entry["columns"].append(attname if attname is not None else "(expression)")

    result: list[IndexInfo] = []
    for name, entry in grouped.items():
        if not entry["columns"]:
            continue
        result.append(
            IndexInfo(
                name=name,
                table=entry["table"],
                columns=tuple(entry["columns"]),
                is_unique=entry["is_unique"],
                is_primary=entry["is_primary"],
            )
        )
    return result


def fetch_index_usage(connection: psycopg.Connection) -> list[IndexUsage]:
    """Read per-index scan counts from pg_stat_user_indexes.

    Raises:
        DatabaseConnectionError: If the statistics query fails.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(_USAGE_SQL)
            rows = cursor.fetchall()
    except psycopg.Error as exc:
        raise DatabaseConnectionError(
            "Could not read index usage statistics", details={"reason": str(exc)}
        ) from exc

    return [
        IndexUsage(name=name, table=table, scan_count=scans or 0)
        for name, table, scans in rows
    ]