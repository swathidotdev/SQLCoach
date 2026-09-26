"""Anti-pattern analyzer.

Parses each query once into a `ParsedQuery` and runs every registered
`AntiPatternDetector` over the whole workload, collecting their findings
(FR-3.6). All of this is static -- no database or execution plan is
required (NFR-3.6.1).

Parsing happens here, once per query, so detectors never re-parse; the
shared AST is handed to each detector via `ParsedQuery`.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlglot
from sqlglot.errors import ParseError as SqlglotParseError

from sqlcoach.advisor.anti_patterns.base import (
    AntiPatternDetector,
    AntiPatternFinding,
    ParsedQuery,
)
from sqlcoach.advisor.anti_patterns.leading_wildcard_like import (
    LeadingWildcardLikeDetector,
)
from sqlcoach.advisor.anti_patterns.n_plus_one import (
    DEFAULT_MIN_OCCURRENCES,
    NPlusOneDetector,
)
from sqlcoach.advisor.anti_patterns.order_by_random import OrderByRandomDetector
from sqlcoach.advisor.anti_patterns.select_star import SelectStarDetector
from sqlcoach.models.query import Query
from sqlcoach.parser.sql_ast_utils import DIALECT

logger = logging.getLogger(__name__)


def default_detectors(
    n_plus_one_min_occurrences: int = DEFAULT_MIN_OCCURRENCES,
) -> tuple[AntiPatternDetector, ...]:
    """Return the default set of anti-pattern detectors.

    This is the single registration point (OCP, US8.5). The N+1
    detector's occurrence threshold is the one piece of per-run config
    an anti-pattern detector needs, so it is passed here; production
    supplies settings.n_plus_one_min_occurrences.
    """
    return (
        SelectStarDetector(),
        LeadingWildcardLikeDetector(),
        OrderByRandomDetector(),
        NPlusOneDetector(min_occurrences=n_plus_one_min_occurrences),
    )


class AntiPatternAnalyzer:
    """Runs anti-pattern detectors across a workload of queries."""

    def __init__(
        self, detectors: Sequence[AntiPatternDetector] | None = None
    ) -> None:
        """Create an analyzer.

        Args:
            detectors: The detectors to run. Defaults to
                `default_detectors()`. Injecting a custom sequence keeps
                the analyzer testable in isolation and lets the service
                pass detectors configured from Settings.
        """
        self._detectors: tuple[AntiPatternDetector, ...] = (
            tuple(detectors) if detectors is not None else default_detectors()
        )

    @property
    def detectors(self) -> tuple[AntiPatternDetector, ...]:
        """The detectors this analyzer will run."""
        return self._detectors

    def analyze(self, queries: Sequence[Query]) -> list[AntiPatternFinding]:
        """Analyze a workload of queries for anti-patterns.

        Args:
            queries: The parsed queries to inspect.

        Returns:
            All anti-pattern findings from all detectors, in detector-
            registration order.
        """
        parsed = [self._parse(query) for query in queries]
        findings: list[AntiPatternFinding] = []
        for detector in self._detectors:
            findings.extend(detector.detect(parsed))
        return findings

    @staticmethod
    def _parse(query: Query) -> ParsedQuery:
        """Parse a query once; unparseable queries yield a None AST."""
        try:
            statement = sqlglot.parse_one(query.text, read=DIALECT)
        except SqlglotParseError:
            logger.debug(
                "Unparseable query skipped for anti-pattern analysis: %s",
                query.source_location or "unknown location",
            )
            statement = None
        return ParsedQuery(query, statement)