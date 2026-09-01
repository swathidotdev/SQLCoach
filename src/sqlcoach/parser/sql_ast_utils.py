"""Shared sqlglot AST helpers.

Every parser and database reader that turns SQL text into a `Query`
needs the same three derived facts: a normalized statement type, the
set of referenced tables, and a canonical (re-generated) form of the
statement for fingerprinting. Those are produced here once, as
`StatementMetadata`, rather than being re-derived independently in
`SqlFileParser`, `LogParser`, and the `pg_stat_statements` reader.
"""

from __future__ import annotations

from typing import NamedTuple, Optional

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError as SqlglotParseError

DIALECT = "postgres"

_SNIPPET_MAX_LENGTH = 80


class StatementMetadata(NamedTuple):
    """Facts derived from a parsed SQL statement.

    Attributes:
        statement_type: Normalized statement type keyword (e.g.
            "SELECT"). None when the text could not be parsed.
        referenced_tables: Distinct table names in first-seen order.
            Empty when unparseable or when no tables are referenced.
        normalized_text: The statement re-generated from its AST, so
            that semantically identical queries written with different
            whitespace, casing, or aliasing share one representation.
            Used as a fingerprint by workload-level analysis (e.g. the
            N+1 detector in Sprint 8). None when unparseable.
    """

    statement_type: Optional[str]
    referenced_tables: tuple[str, ...]
    normalized_text: Optional[str]


#: The metadata produced when a statement could not be parsed at all.
UNPARSED = StatementMetadata(statement_type=None, referenced_tables=(), normalized_text=None)


def extract_tables(statement: exp.Expression) -> tuple[str, ...]:
    """Return distinct table names referenced by `statement`, in
    first-seen order.
    """
    seen: list[str] = []
    for table in statement.find_all(exp.Table):
        name = table.name
        if name and name not in seen:
            seen.append(name)
    return tuple(seen)


def statement_type(statement: exp.Expression) -> str:
    """Return a normalized statement type keyword, e.g. "SELECT"."""
    return type(statement).__name__.upper()


def describe(statement: exp.Expression) -> StatementMetadata:
    """Derive all metadata from an already-parsed statement."""
    return StatementMetadata(
        statement_type=statement_type(statement),
        referenced_tables=extract_tables(statement),
        normalized_text=statement.sql(dialect=DIALECT),
    )


def describe_sql(sql_text: str) -> StatementMetadata:
    """Best-effort metadata extraction from raw SQL text.

    Never raises. Callers that already hold a parsed statement should
    use `describe()` instead; this variant exists for sources whose
    primary job succeeded without a parse (log entries, normalized
    `pg_stat_statements` text), where a parse failure is a minor
    enrichment miss rather than a resilience-relevant failure.
    """
    try:
        statement = sqlglot.parse_one(sql_text, read=DIALECT)
    except SqlglotParseError:
        return UNPARSED
    if statement is None:
        return UNPARSED
    return describe(statement)


def snippet(text: str) -> str:
    """Truncate `text` to a short, single warning-message-friendly snippet."""
    stripped = text.strip()
    if len(stripped) <= _SNIPPET_MAX_LENGTH:
        return stripped
    return stripped[:_SNIPPET_MAX_LENGTH] + "..."