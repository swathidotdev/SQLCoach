"""ORDER BY RANDOM() detector (US8.3, FR-3.6.3).

Flags queries that sort by ``RANDOM()``. PostgreSQL must assign a random
value to every candidate row and sort the whole set on each execution,
which is expensive on large tables -- and it can't be served by any
index. It's typically used to pull a random sample, for which
TABLESAMPLE or a keyset approach is far cheaper.
"""

from __future__ import annotations

from typing import Sequence

from sqlglot import exp

from sqlcoach.advisor.anti_patterns.base import AntiPatternFinding, ParsedQuery
from sqlcoach.analyzer.base import Severity

_CODE = "ORDER_BY_RANDOM"


class OrderByRandomDetector:
    """Detects ORDER BY RANDOM() usage."""

    name = "order_by_random"

    def detect(
        self, parsed_queries: Sequence[ParsedQuery]
    ) -> list[AntiPatternFinding]:
        findings: list[AntiPatternFinding] = []
        for parsed in parsed_queries:
            if parsed.statement is None:
                continue
            if not self._has_order_by_random(parsed.statement):
                continue
            findings.append(
                AntiPatternFinding(
                    code=_CODE,
                    detector=self.name,
                    severity=Severity.MEDIUM,
                    summary=(
                        "ORDER BY RANDOM() assigns a random value to every row and sorts "
                        "the entire result on each execution -- expensive at scale, and "
                        "not index-servable. For sampling, prefer TABLESAMPLE or a "
                        "keyset/offset approach."
                    ),
                    source_location=parsed.query.source_location,
                )
            )
        return findings

    @staticmethod
    def _has_order_by_random(statement: exp.Expression) -> bool:
        for order in statement.find_all(exp.Order):
            for ordered in order.expressions:
                if isinstance(ordered.this, exp.Rand):
                    return True
        return False