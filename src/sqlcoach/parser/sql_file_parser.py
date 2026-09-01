"""SQL file parser.

Parses `.sql` files into `Query` objects (FR-3.1.1) and extracts
statement type, referenced tables, and a normalized form from the
resulting AST (FR-3.1.3).

Statement splitting is done with sqlglot's *tokenizer* rather than by
parsing the file as a whole or by naive `str.split(";")`. The
tokenizer understands string literals, dollar-quoted bodies, and
comments, so it finds true statement boundaries -- and because each
token carries its character offset and line number, every statement
can be sliced out of the original text with its real line number
intact. That gives three things at once: correct boundaries, verbatim
source text preserved in `Query.text`, and accurate line numbers in
resilience warnings (NFR-3.1.2).

Resilience (FR-3.1.4) is layered the same way as elsewhere in the
codebase -- strict path first, fallback only on failure:

1. Tokenize the whole file and split on top-level semicolons, then
   parse each statement independently. One unparseable statement is
   logged and skipped; the rest of the file still yields queries.
2. If tokenization itself fails (e.g. an unterminated string literal
   makes the file untokenizable), fall back to naive semicolon
   splitting so the readable portion is still attempted. That
   fallback does not handle dollar-quoted bodies containing
   semicolons -- an accepted, documented limitation for input that is
   already lexically broken.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Union

import sqlglot
from sqlglot.errors import ParseError as SqlglotParseError, TokenError as SqlglotTokenError
from sqlglot.tokens import Token, TokenType

from sqlcoach.models.query import Query, QuerySource
from sqlcoach.parser.sql_ast_utils import DIALECT, describe, snippet

logger = logging.getLogger(__name__)


class _StatementSpan:
    """One statement's verbatim text plus its 1-based starting line."""

    __slots__ = ("text", "line_number")

    def __init__(self, text: str, line_number: int) -> None:
        self.text = text
        self.line_number = line_number


def _line_number_at(text: str, offset: int) -> int:
    """Return the 1-based line number of `offset` within `text`."""
    return text.count("\n", 0, offset) + 1


def _span_from(text: str, start: int, end: int) -> Optional[_StatementSpan]:
    """Build a span for `text[start:end]`, or None if it is blank.

    The reported line number points at the first non-whitespace
    character of the statement, not at the boundary left behind by the
    previous semicolon.
    """
    raw = text[start:end]
    if not raw.strip():
        return None
    content_offset = start + (len(raw) - len(raw.lstrip()))
    return _StatementSpan(raw.strip(), _line_number_at(text, content_offset))


def _split_by_tokenizer(text: str) -> list[_StatementSpan]:
    """Split `text` into statements using sqlglot's tokenizer.

    Raises:
        SqlglotTokenError: If the text cannot be tokenized at all.
    """
    tokens: list[Token] = sqlglot.tokenize(text, read=DIALECT)

    spans: list[_StatementSpan] = []
    start = 0
    for token in tokens:
        if token.token_type is not TokenType.SEMICOLON:
            continue
        span = _span_from(text, start, token.start)
        if span is not None:
            spans.append(span)
        start = token.end + 1

    trailing = _span_from(text, start, len(text))
    if trailing is not None:
        spans.append(trailing)
    return spans


def _split_naively(text: str) -> list[_StatementSpan]:
    """Split `text` on every semicolon, ignoring quoting rules.

    Used only when tokenization fails outright -- see module docstring.
    """
    spans: list[_StatementSpan] = []
    start = 0
    for chunk in text.split(";"):
        span = _span_from(text, start, start + len(chunk))
        if span is not None:
            spans.append(span)
        start += len(chunk) + 1  # +1 accounts for the removed ";"
    return spans


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
            One Query per successfully parsed statement, each holding
            the statement's verbatim source text. Statements that fail
            to parse are skipped and logged; they never raise out of
            this method.
        """
        path = Path(source)
        text = path.read_text(encoding="utf-8")
        return self.parse_text(text, source_location=str(path))

    def parse_text(self, text: str, *, source_location: str) -> list[Query]:
        """Parse SQL `text` that has already been read into memory.

        Exposed publicly so callers holding SQL from somewhere other
        than a file on disk (a here-doc, a code review diff, a test)
        can reuse the same splitting and resilience behavior.
        """
        if not text.strip():
            return []

        try:
            spans = _split_by_tokenizer(text)
        except SqlglotTokenError as exc:
            logger.warning(
                "%s could not be tokenized (%s); falling back to naive semicolon "
                "splitting, which may mis-split dollar-quoted bodies",
                source_location,
                str(exc).splitlines()[0],
            )
            spans = _split_naively(text)

        queries: list[Query] = []
        for span in spans:
            query = self._build_query(span, source_location)
            if query is not None:
                queries.append(query)
        return queries

    def _build_query(self, span: _StatementSpan, source_location: str) -> Optional[Query]:
        """Turn one statement span into a Query, or None if it won't parse."""
        try:
            statement = sqlglot.parse_one(span.text, read=DIALECT)
        except SqlglotParseError as exc:
            logger.warning(
                "Skipping unparseable statement in %s at line %d: %s | snippet: %r",
                source_location,
                span.line_number,
                str(exc).splitlines()[0],
                snippet(span.text),
            )
            return None

        if statement is None:
            return None

        metadata = describe(statement)
        return Query(
            text=span.text,
            normalized_text=metadata.normalized_text,
            source=QuerySource.SQL_FILE,
            source_location=f"{source_location}:line {span.line_number}",
            statement_type=metadata.statement_type,
            referenced_tables=metadata.referenced_tables,
        )