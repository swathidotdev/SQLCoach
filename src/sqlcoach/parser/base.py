"""Abstract parser interface.

Defines the contract every concrete parser (SQL file, log file,
pg_stat_statements, and any future input format) implements to
produce `Query` objects (FR-2.8). Modeled as a `Protocol` rather than
an abstract base class: structural typing lets concrete parsers exist
without inheriting from this module at all, keeping the framework
extensible to new formats without ever needing to modify this file
(NFR-2.3, Open/Closed Principle).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, Union, runtime_checkable

from sqlcoach.models.query import Query


@runtime_checkable
class Parser(Protocol):
    """Structural contract for anything that turns a source into Query objects.

    Concrete implementations (Sprint 3: `SqlFileParser`, `LogParser`)
    do not need to inherit from this class -- any object exposing a
    matching `parse` method satisfies this Protocol.
    """

    def parse(self, source: Union[str, Path]) -> list[Query]:
        """Parse `source` into zero or more Query objects.

        Args:
            source: A file path, or raw text content, depending on
                the concrete parser's documented input contract.

        Returns:
            The Query objects extracted from `source`. An empty list
            is a valid result (e.g. an empty file); malformed-input
            handling is left to each concrete parser to define, per
            FR-3.1's resilient-error-reporting requirement.
        """
        ...