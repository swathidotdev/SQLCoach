"""Index catalog row models.

Structured shapes for what the index-catalog readers return. Kept in
`models/` (not `database/`) so both the database layer that produces them
and the advisor that consumes them depend inward on the domain, never
advisor -> database.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class IndexInfo(BaseModel):
    """One index's structural definition, from the catalog.

    Attributes:
        name: The index's name.
        table: The table it indexes.
        columns: Its key columns, in index order (order is significant
            for prefix-redundancy comparison).
        is_unique: Whether it is a UNIQUE index.
        is_primary: Whether it backs a PRIMARY KEY.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    table: str
    columns: tuple[str, ...] = Field(min_length=1)
    is_unique: bool = False
    is_primary: bool = False


class IndexUsage(BaseModel):
    """One index's usage statistics, from pg_stat_user_indexes.

    Attributes:
        name: The index's name.
        table: The table it indexes.
        scan_count: Number of index scans recorded (idx_scan). A low or
            zero count is a signal -- not proof -- that the index is
            unused, since statistics can be reset.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    table: str
    scan_count: int = Field(ge=0)