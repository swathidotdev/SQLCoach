"""CREATE INDEX statement generation (US7.4, FR-3.5.4).

Generates ready-to-run `CREATE INDEX` SQL for a recommendation. The
tool only ever *generates* this text -- it never executes it
(NFR-3.5.1); applying the index is always left to the user.

Identifiers are emitted unquoted, which is correct for ordinary
lowercase names. Mixed-case or reserved-word table/column names would
need double-quoting; that refinement is noted and deferred, as the
common case is plain identifiers.
"""

from __future__ import annotations

from collections.abc import Sequence

# PostgreSQL truncates identifiers at NAMEDATALEN - 1 (63 by default).
# A generated name longer than this is truncated so the statement stays
# valid; collisions from truncation are vanishingly unlikely for real
# table/column names and are accepted rather than complicating naming.
_MAX_IDENTIFIER_LENGTH = 63


def index_name(table: str, columns: Sequence[str]) -> str:
    """Return a deterministic index name like ``idx_orders_user_id``.

    Only the key columns contribute to the name; INCLUDE columns do not,
    to keep names stable and readable.
    """
    name = "_".join(["idx", table, *columns])
    return name[:_MAX_IDENTIFIER_LENGTH]


def generate_create_index(
    table: str,
    columns: Sequence[str],
    included_columns: Sequence[str] = (),
) -> str:
    """Generate a CREATE INDEX statement.

    Args:
        table: The table to index.
        columns: The ordered key columns.
        included_columns: Optional non-key columns for an INCLUDE clause
            (a covering index).

    Returns:
        A single, ready-to-run CREATE INDEX statement ending in ';'.
    """
    if not columns:
        raise ValueError("an index needs at least one key column")

    name = index_name(table, columns)
    key_columns = ", ".join(columns)
    statement = f"CREATE INDEX {name} ON {table} ({key_columns})"
    if included_columns:
        statement += f" INCLUDE ({', '.join(included_columns)})"
    return statement + ";"