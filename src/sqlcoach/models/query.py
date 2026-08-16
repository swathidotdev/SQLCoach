"""Query domain model.

Represents a single SQL query along with where it came from and any
metadata collected about it. This is the common data contract that
every input source (SQL file, log file, live database,
pg_stat_statements) normalizes into (FR-2.1).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuerySource(str, Enum):
    """Where a Query originated from."""

    SQL_FILE = "sql_file"
    LOG_FILE = "log_file"
    LIVE_DATABASE = "live_database"
    PG_STAT_STATEMENTS = "pg_stat_statements"


class Query(BaseModel):
    """A single SQL query and metadata about its origin and observed behavior.

    Attributes:
        text: The raw SQL text of the query.
        source: Where this query was discovered.
        source_location: Optional human-readable pointer to where the
            query came from (e.g. a file path and line number, or a
            log timestamp). Purely informational.
        execution_time_ms: Observed execution time in milliseconds, if
            known at construction time (e.g. from a Postgres log line
            or pg_stat_statements). None if not yet measured.
        call_count: Number of times this query was observed/executed,
            when known (e.g. from pg_stat_statements). Defaults to 1
            for a single observed occurrence.
        statement_type: Normalized statement type keyword (e.g.
            "SELECT", "INSERT", "UPDATE", "DELETE"), when derivable
            from parsing (FR-3.1.3). None if not yet determined.
        referenced_tables: Table names referenced by this query, when
            derivable from parsing (FR-3.1.3). Empty tuple if not yet
            determined, or if the statement references no tables
            (e.g. "SELECT 1").
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    source: QuerySource
    source_location: Optional[str] = None
    execution_time_ms: Optional[float] = Field(default=None, ge=0)
    call_count: int = Field(default=1, ge=1)
    statement_type: Optional[str] = None
    referenced_tables: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("text")
    @classmethod
    def _validate_text_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be empty")
        return value