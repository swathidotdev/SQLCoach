"""N+1 query-pattern detector (US8.4, FR-3.6.4).

Flags groups of near-identical queries that differ only in their literal
values -- the signature of an N+1 pattern, where application code issues
one query per row inside a loop instead of a single batched query.

Detection clusters queries by a *structure fingerprint*: the query
re-generated from its AST with every literal replaced by a placeholder,
so ``WHERE user_id = 1`` and ``WHERE user_id = 2`` collapse to the same
fingerprint while structurally different queries stay distinct. A
cluster whose size reaches the configured threshold is reported. The
fingerprint also normalizes whitespace and casing (a side effect of
AST re-generation), so purely cosmetic differences don't split a
cluster.
"""

from __future__ import annotations

from typing import Optional, Sequence

from sqlglot import exp

from sqlcoach.advisor.anti_patterns.base import AntiPatternFinding, ParsedQuery
from sqlcoach.analyzer.base import Severity
from sqlcoach.parser.sql_ast_utils import DIALECT

_CODE = "N_PLUS_ONE"

#: Default cluster size at or above which a repeated query is treated as
#: an N+1 pattern. Kept in sync with Settings via config.
DEFAULT_MIN_OCCURRENCES = 5


def _structure_fingerprint(parsed: ParsedQuery) -> str:
    """Return a literal-stripped, canonicalized fingerprint of a query.

    Uses sqlglot's `transform`, which copies the tree, so the shared
    parsed AST handed to other detectors is never mutated. Unparseable
    queries fall back to the query's own text fingerprint.
    """
    if parsed.statement is None:
        return parsed.query.fingerprint
    stripped = parsed.statement.transform(
        lambda node: exp.Placeholder() if isinstance(node, exp.Literal) else node
    )
    return stripped.sql(dialect=DIALECT)


def _first_table(parsed: ParsedQuery) -> Optional[str]:
    """A representative table name for the cluster's message, if known."""
    if parsed.query.referenced_tables:
        return parsed.query.referenced_tables[0]
    if parsed.statement is not None:
        for table in parsed.statement.find_all(exp.Table):
            if table.name:
                return table.name
    return None


class NPlusOneDetector:
    """Detects repeated near-identical queries across a workload."""

    def __init__(self, min_occurrences: int = DEFAULT_MIN_OCCURRENCES) -> None:
        """Create the detector.

        Args:
            min_occurrences: The cluster size at or above which a
                repeated query is flagged. Production passes
                settings.n_plus_one_min_occurrences.
        """
        self._min_occurrences = min_occurrences

    name = "n_plus_one"

    def detect(
        self, parsed_queries: Sequence[ParsedQuery]
    ) -> list[AntiPatternFinding]:
        clusters: dict[str, list[ParsedQuery]] = {}
        for parsed in parsed_queries:
            clusters.setdefault(_structure_fingerprint(parsed), []).append(parsed)

        findings: list[AntiPatternFinding] = []
        for group in clusters.values():
            if len(group) < self._min_occurrences:
                continue
            first = group[0]
            relation = _first_table(first)
            location = f" on {relation}" if relation else ""
            findings.append(
                AntiPatternFinding(
                    code=_CODE,
                    detector=self.name,
                    severity=Severity.MEDIUM,
                    summary=(
                        f"{len(group)} near-identical queries{location} differ only in "
                        f"their literal values -- the signature of an N+1 pattern, where "
                        f"the application issues one query per row in a loop. Batch them "
                        f"into a single query using IN (...) or a JOIN."
                    ),
                    source_location=first.query.source_location,
                    relation_name=relation,
                    metrics={"occurrences": len(group)},
                )
            )
        return findings