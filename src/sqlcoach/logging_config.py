"""Centralized logging configuration for SQLCoach.

All modules obtain their logger via `logging.getLogger(__name__)` and
rely on this module to configure the root logger's handlers, format,
and level exactly once per process (US1.3). Importing this module has
no side effects (NFR-1.4) -- logging is only configured when
`configure_logging()` is called explicitly.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

# Marker attribute used to identify handlers this module has installed,
# so repeated calls to configure_logging() reconfigure cleanly instead
# of stacking duplicate handlers on the root logger.
_HANDLER_MARKER = "_sqlcoach_managed_handler"


class _JsonFormatter(logging.Formatter):
    """Renders each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    """Configure the root logger's level and output format.

    Safe to call multiple times: each call replaces any handler
    previously installed by this function rather than stacking a new
    one on top, so tests and CLI re-invocations don't produce
    duplicate log lines.

    Args:
        level: Minimum log level to emit. One of DEBUG, INFO,
            WARNING, ERROR, CRITICAL (case-insensitive).
        json_output: When True, emit structured single-line JSON logs
            (for CI/machine consumption). When False, emit
            human-readable text (for interactive use).

    Raises:
        ValueError: If `level` is not a recognized log level.
    """
    normalized_level = level.upper()
    if normalized_level not in _VALID_LOG_LEVELS:
        valid = ", ".join(sorted(_VALID_LOG_LEVELS))
        raise ValueError(f"level must be one of: {valid} (got {level!r})")

    root_logger = logging.getLogger()

    # Remove only handlers this module previously installed -- never
    # touch handlers a host application or test framework may have
    # attached for its own purposes.
    for handler in list(root_logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            root_logger.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stderr)
    setattr(handler, _HANDLER_MARKER, True)

    if json_output:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    root_logger.addHandler(handler)
    root_logger.setLevel(normalized_level)