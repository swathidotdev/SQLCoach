"""PostgreSQL log parser.

Parses PostgreSQL log text into `Query` objects with observed
execution time (FR-3.1.2). Supports two formats:

1. The simplified block format documented in ABOUT_PROJECT.md:

       Query:
       SELECT * FROM orders WHERE user_id = 10;

       Execution Time:
       820 ms

2. The standard PostgreSQL slow-query log format produced by
   `log_min_duration_statement`, assuming a log_line_prefix beginning
   with an ISO-style timestamp (the common default shape, e.g.
   `%m [%p] `):

       2024-01-15 10:23:45.123 UTC [12345] LOG:  duration: 820.123 ms  statement: SELECT * FROM orders WHERE user_id = 10;

   Multi-line statements are supported: any line following a
   "statement:" line that does not itself look like the start of a
   new timestamped log entry is treated as a continuation of the same
   statement. A heavily customized log_line_prefix that doesn't start
   with a timestamp will not be recognized as an entry boundary --
   this is a known, documented limitation rather than an attempt at
   full log_line_prefix generality.

A given file is assumed to be one format or the other, not a mix: the
simplified block format is tried first, and the duration-log format is
only attempted if no blocks were found.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional, Union

import sqlglot
from sqlglot.errors import ParseError as SqlglotParseError

from sqlcoach.models.query import Query, QuerySource
from sqlcoach.parser.sql_ast_utils import extract_tables, statement_type

logger = logging.getLogger(__name__)

_DIALECT = "postgres"

_SIMPLE_BLOCK_PATTERN = re.compile(
    r"Query:\s*\n(?P<sql>.*?)\n\s*\nExecution Time:\s*\n(?P<time>[\d.]+)\s*ms",
    re.DOTALL,
)

_DURATION_LINE_PATTERN = re.compile(
    r"duration:\s*(?P<time>[\d.]+)\s*ms\s+statement:\s*(?P<rest>.*)$"
)

_TIMESTAMP_ENTRY_START_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}")


def _try_enrich_with_parse(sql_text: str) -> tuple[Optional[str], tuple[str, ...]]:
    """Best-effort statement_type/referenced_tables extraction for SQL
    text pulled out of a log entry.

    Unlike SqlFileParser, a failure here is not logged as a warning:
    the execution-time extraction (this parser's primary job) already
    succeeded, so a SQL parse failure on the extracted text is a minor
    enrichment miss, not a resilience-relevant failure.
    """
    try:
        statement = sqlglot.parse_one(sql_text, read=_DIALECT)
    except SqlglotParseError:
        return None, ()
    return statement_type(statement), extract_tables(statement)


class LogParser:
    """Parses PostgreSQL log text into `Query` objects.

    Malformed or unrecognized entries are simply not matched by either
    format's pattern and are skipped -- there is no concept of a
    "broken" log entry the way there is a broken SQL statement, since
    log parsing here works by pattern matching rather than a strict
    grammar (FR-3.1.4 is satisfied by construction: unmatched text
    never raises, it's just not extracted).
    """

    def parse(self, source: Union[str, Path]) -> list[Query]:
        """Parse the log file at `source` into Query objects.

        Args:
            source: Path to a PostgreSQL log file (or log excerpt).

        Returns:
            One Query per recognized log entry, in either supported
            format. Never raises on unrecognized or malformed content.
        """
        path = Path(source)
        text = path.read_text(encoding="utf-8")
        return self._parse_text(text, source_location=str(path))

    def _parse_text(self, text: str, *, source_location: str) -> list[Query]:
        simple_results = self._parse_simple_blocks(text, source_location)
        if simple_results:
            return simple_results
        return self._parse_duration_log(text, source_location)

    def _parse_simple_blocks(self, text: str, source_location: str) -> list[Query]:
        queries: list[Query] = []
        for index, match in enumerate(_SIMPLE_BLOCK_PATTERN.finditer(text), start=1):
            sql_text = match.group("sql").strip()
            raw_time = match.group("time")
            if not sql_text:
                continue
            try:
                execution_time_ms = float(raw_time)
            except ValueError:
                logger.warning(
                    "Skipping log block %d in %s: unparseable execution time %r",
                    index,
                    source_location,
                    raw_time,
                )
                continue
            statement_type_value, referenced_tables = _try_enrich_with_parse(sql_text)
            queries.append(
                Query(
                    text=sql_text,
                    source=QuerySource.LOG_FILE,
                    source_location=f"{source_location}:block {index}",
                    execution_time_ms=execution_time_ms,
                    statement_type=statement_type_value,
                    referenced_tables=referenced_tables,
                )
            )
        return queries

    def _parse_duration_log(self, text: str, source_location: str) -> list[Query]:
        queries: list[Query] = []
        lines = text.splitlines()
        index = 0
        while index < len(lines):
            match = _DURATION_LINE_PATTERN.search(lines[index])
            if match is None:
                index += 1
                continue

            raw_time = match.group("time")
            sql_lines = [match.group("rest")]
            next_index = index + 1
            while next_index < len(lines) and not _TIMESTAMP_ENTRY_START_PATTERN.match(
                lines[next_index]
            ):
                sql_lines.append(lines[next_index])
                next_index += 1

            sql_text = "\n".join(sql_lines).strip()
            line_number = index + 1

            try:
                execution_time_ms = float(raw_time)
            except ValueError:
                logger.warning(
                    "Skipping log entry at %s line %d: unparseable execution time %r",
                    source_location,
                    line_number,
                    raw_time,
                )
                index = next_index
                continue

            if sql_text:
                statement_type_value, referenced_tables = _try_enrich_with_parse(sql_text)
                queries.append(
                    Query(
                        text=sql_text,
                        source=QuerySource.LOG_FILE,
                        source_location=f"{source_location}:line {line_number}",
                        execution_time_ms=execution_time_ms,
                        statement_type=statement_type_value,
                        referenced_tables=referenced_tables,
                    )
                )
            index = next_index
        return queries