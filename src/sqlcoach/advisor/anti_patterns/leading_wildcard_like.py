"""Leading-wildcard LIKE detector (US8.2, FR-3.6.2).

Flags LIKE/ILIKE predicates whose pattern begins with a wildcard
(``'%value'``). A leading ``%`` gives the b-tree index no known prefix
to seek on, so PostgreSQL falls back to scanning every row. Trailing-
only patterns (``'value%'``) are fine and are not flagged, and a
parameterized pattern (``LIKE $1``) is skipped because its value can't
be known statically.

Only predicates in WHERE and join ON clauses are inspected -- a LIKE in
a SELECT projection is a computed value, not a filter, so flagging it
would be a false positive.
"""

from __future__ import annotations

from typing import Optional, Sequence

from sqlglot import exp

from sqlcoach.advisor.anti_patterns.base import AntiPatternFinding, ParsedQuery
from sqlcoach.analyzer.base import Severity

_CODE = "LEADING_WILDCARD_LIKE"


def _predicate_scopes(statement: exp.Expression) -> list[exp.Expression]:
    """WHERE clauses and join ON conditions -- where filtering LIKEs live."""
    scopes: list[exp.Expression] = list(statement.find_all(exp.Where))
    for join in statement.find_all(exp.Join):
        on = join.args.get("on")
        if on is not None:
            scopes.append(on)
    return scopes


def _has_leading_wildcard(like: exp.Expression) -> bool:
    """True if the LIKE pattern is a string literal starting with '%'."""
    pattern = like.expression
    if isinstance(pattern, exp.Literal) and pattern.is_string:
        return pattern.this.startswith("%")
    return False  # non-literal (e.g. a bind parameter): can't tell -> skip


def _column_label(like: exp.Expression) -> Optional[str]:
    """The name of the column being matched, if the left side is a column."""
    target = like.this
    if isinstance(target, exp.Column):
        return target.name
    return None


class LeadingWildcardLikeDetector:
    """Detects LIKE/ILIKE patterns that begin with a wildcard."""

    name = "leading_wildcard_like"

    def detect(
        self, parsed_queries: Sequence[ParsedQuery]
    ) -> list[AntiPatternFinding]:
        findings: list[AntiPatternFinding] = []
        for parsed in parsed_queries:
            if parsed.statement is None:
                continue

            seen: set[Optional[str]] = set()
            for scope in _predicate_scopes(parsed.statement):
                for like in scope.find_all(exp.Like, exp.ILike):
                    if not _has_leading_wildcard(like):
                        continue
                    label = _column_label(like)
                    if label in seen:
                        continue
                    seen.add(label)

                    column_note = f" on {label}" if label else ""
                    relation = (
                        like.this.table or None
                        if isinstance(like.this, exp.Column)
                        else None
                    )
                    findings.append(
                        AntiPatternFinding(
                            code=_CODE,
                            detector=self.name,
                            severity=Severity.MEDIUM,
                            summary=(
                                f"A LIKE pattern{column_note} begins with a wildcard "
                                f"('%...'), so a b-tree index can't be used and the query "
                                f"scans every row. Consider a trigram (pg_trgm) index or "
                                f"full-text search."
                            ),
                            source_location=parsed.query.source_location,
                            relation_name=relation,
                        )
                    )
        return findings