"""SQL file parser.

Parses `.sql` files into `Query` objects using sqlglot, which
correctly handles statement boundaries inside string literals,
dollar-quoted strings, and comments -- something naive
semicolon-splitting gets wrong (FR-3.1.1). Also extracts statement
type and referenced tables from the resulting AST (FR-3.1.3).

Resilience note (FR-3.1.4): the happy path is a single strict parse of
the whole file, which is what gives correct handling of dollar-quoted
bodies etc. If that fails, this falls back to naive semicolon
splitting so the rest of the file can still be attempted. That
fallback does NOT correctly handle a dollar-quoted body containing a
semicolon if the file *also* has a genuine syntax error elsewhere --
that combination is rare, and correctly handling it would require
depending on unstable/internal sqlglot APIs, so it is accepted as a
documented limitation rather than solved here.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Union

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError as SqlglotParseError

from sqlcoach.models.query import Query, QuerySource

logger = logging.getLogger(__name__)

_DIALECT = "postgres"
_SNIPPET_MAX_LENGTH = 80


def _extract_tables(statement: exp.Expression) -> tuple[str, ...]:
    """Return distinct table names referenced by `statement`, in
    first-seen order.
    """
    seen: list[str] = []
    for table in statement.find_all(exp.Table):
        name = table.name
        if name and name not in seen:
            seen.append(name)
    return tuple(seen)


def _statement_type(statement: exp.Expression) -> str:
    """Return a normalized statement type keyword, e.g. "SELECT"."""
    return type(statement).__name__.upper()


def _snippet(text: str) -> str:
    stripped = text.strip()
    if len(stripped) <= _SNIPPET_MAX_LENGTH:
        return stripped
    return stripped[:_SNIPPET_MAX_LENGTH] + "..."


def _split_with_line_numbers(text: str) -> list[tuple[int, str]]:
    """Naively split `text` on semicolons, pairing each resulting chunk
    with the 1-based line number where its actual (non-whitespace)
    content starts in the original text. Used only as the FR-3.1.4
    fallback path -- see module docstring for its known limitation
    with dollar-quoted bodies.
    """
    chunks: list[tuple[int, str]] = []
    offset = 0
    for raw_piece in text.split(";"):
        leading_whitespace_length = len(raw_piece) - len(raw_piece.lstrip())
        content_offset = offset + leading_whitespace_length
        start_line = text.count("\n", 0, content_offset) + 1
        chunks.append((start_line, raw_piece))
        offset += len(raw_piece) + 1  # +1 accounts for the removed ";"
    return chunks


class SqlFileParser:
    """Parses a `.sql` file's statements into `Query` objects.

    Malformed statements are logged as warnings (with line number and
    a text snippet) and skipped, rather than aborting the whole parse
    (FR-3.1.4) -- one bad statement should never block analysis of the
    rest of the file.
    """

    def parse(self, source: Union[str, Path]) -> list[Query]:
        """Parse the `.sql` file at `source` into Query objects.

        Args:
            source: Path to a `.sql` file.

        Returns:
            One Query per successfully parsed statement. Statements
            that fail to parse are skipped and logged; they never
            raise out of this method.
        """
        path = Path(source)
        text = path.read_text(encoding="utf-8")
        return self._parse_text(text, source_location=str(path))

    def _parse_text(self, text: str, *, source_location: str) -> list[Query]:
        if not text.strip():
            return []

        try:
            statements = sqlglot.parse(
                text, read=_DIALECT, error_level=sqlglot.ErrorLevel.RAISE
            )
        except SqlglotParseError as exc:
            logger.warning(
                "%s did not parse cleanly as a whole (%s); falling back to "
                "per-statement parsing, which may miss statements containing "
                "dollar-quoted bodies with embedded semicolons",
                source_location,
                str(exc).splitlines()[0],
            )
            return self._fallback_parse(text, source_location)

        return [
            self._build_query(statement, source_location, index)
            for index, statement in enumerate(statements, start=1)
            if statement is not None
        ]

    def _fallback_parse(self, text: str, source_location: str) -> list[Query]:
        queries: list[Query] = []
        for index, (line_number, raw_chunk) in enumerate(
            _split_with_line_numbers(text), start=1
        ):
            stripped = raw_chunk.strip()
            if not stripped:
                continue
            try:
                statement = sqlglot.parse_one(stripped, read=_DIALECT)
            except SqlglotParseError as exc:
                logger.warning(
                    "Skipping unparseable statement in %s at line %d: %s | snippet: %r",
                    source_location,
                    line_number,
                    str(exc).splitlines()[0],
                    _snippet(stripped),
                )
                continue
            queries.append(
                self._build_query(statement, source_location, index, line_number=line_number)
            )
        return queries

    def _build_query(
        self,
        statement: exp.Expression,
        source_location: str,
        index: int,
        *,
        line_number: Optional[int] = None,
    ) -> Query:
        location = (
            f"{source_location}:line {line_number}"
            if line_number is not None
            else f"{source_location}:statement {index}"
        )
        return Query(
            text=statement.sql(dialect=_DIALECT),
            source=QuerySource.SQL_FILE,
            source_location=location,
            statement_type=_statement_type(statement),
            referenced_tables=_extract_tables(statement),
        )