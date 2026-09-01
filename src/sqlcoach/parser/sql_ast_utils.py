"""Shared sqlglot AST helpers.

Both `SqlFileParser` and `LogParser` need to derive a normalized
statement type and the set of referenced tables from a parsed
statement, and both need to truncate SQL text into a short snippet for
warning messages. Factored out here rather than duplicated or imported
privately across parser modules.
"""

from __future__ import annotations

from sqlglot import exp

_SNIPPET_MAX_LENGTH = 80


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


def snippet(text: str) -> str:
    """Truncate `text` to a short, single warning-message-friendly snippet."""
    stripped = text.strip()
    if len(stripped) <= _SNIPPET_MAX_LENGTH:
        return stripped
    return stripped[:_SNIPPET_MAX_LENGTH] + "..."