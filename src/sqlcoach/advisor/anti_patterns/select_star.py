"""SELECT * detector (US8.1, FR-3.6.1).

Flags queries whose top-level SELECT projects every column with ``*``
(or ``t.*``). Selecting all columns pulls unneeded data over the wire
and defeats index-only scans, so listing explicit columns is preferred.

Only the *outermost* SELECT's projections are inspected (each arm of a
top-level UNION included). A star nested in a subquery -- or inside a
function such as ``COUNT(*)`` -- is not a SELECT-* and is not flagged,
keeping the detector free of false positives on clean queries.
"""

from __future__ import annotations

from typing import Optional, Sequence

from sqlglot import exp

from sqlcoach.advisor.anti_patterns.base import AntiPatternFinding, ParsedQuery
from sqlcoach.analyzer.base import Severity

_CODE = "SELECT_STAR"


def _top_level_selects(statement: exp.Expression) -> list[exp.Select]:
    """Return the outermost SELECT(s): the statement itself, or the arms
    of a top-level UNION. Subquery SELECTs are intentionally excluded.
    """
    if isinstance(statement, exp.Select):
        return [statement]
    if isinstance(statement, exp.Union):
        return _top_level_selects(statement.this) + _top_level_selects(
            statement.expression
        )
    return []


def _projects_star(select: exp.Select) -> bool:
    """True if a direct projection of `select` is ``*`` or ``t.*``."""
    for projection in select.expressions:
        if isinstance(projection, exp.Star):
            return True
        if isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star):
            return True
    return False


def _first_table(select: exp.Select) -> Optional[str]:
    """Best-effort first table name referenced by the select, for the
    finding's message. None when none is determinable.
    """
    for table in select.find_all(exp.Table):
        if table.name:
            return table.name
    return None


class SelectStarDetector:
    """Detects top-level SELECT * usage."""

    name = "select_star"

    def detect(
        self, parsed_queries: Sequence[ParsedQuery]
    ) -> list[AntiPatternFinding]:
        findings: list[AntiPatternFinding] = []
        for parsed in parsed_queries:
            if parsed.statement is None:
                continue

            relation: Optional[str] = None
            flagged = False
            for select in _top_level_selects(parsed.statement):
                if _projects_star(select):
                    flagged = True
                    relation = relation or _first_table(select)

            if not flagged:
                continue

            location = f" on {relation}" if relation else ""
            findings.append(
                AntiPatternFinding(
                    code=_CODE,
                    detector=self.name,
                    severity=Severity.LOW,
                    summary=(
                        f"SELECT *{location} fetches every column; list only the columns "
                        f"you need to cut I/O and make covering indexes possible."
                    ),
                    source_location=parsed.query.source_location,
                    relation_name=relation,
                )
            )
        return findings