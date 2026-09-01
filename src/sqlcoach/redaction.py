"""Credential redaction utilities.

Ensures PostgreSQL connection strings never reach a log line with
their password intact, regardless of how or where a DSN ends up being
logged (NFR-2.5). This module is deliberately placed at the top level
of the package (a cross-cutting concern), not inside `database/` --
`logging_config.py` needs to use it, and having a foundational,
always-on module depend on a specific feature layer (`database/`)
would invert the intended dependency direction.
"""

from __future__ import annotations

import logging
import re
from typing import Any

_REDACTED = "***REDACTED***"

# Matches the password portion of a libpq-style URI DSN, e.g.
# postgresql://user:password@host:port/dbname
_URI_PASSWORD_PATTERN = re.compile(r"(://[^:/@\s]+:)([^@\s]+)(@)")

# Matches a `password=...` key-value pair in a libpq keyword/value DSN,
# e.g. "host=localhost password=secret dbname=mydb"
_KEYWORD_PASSWORD_PATTERN = re.compile(r"(?i)(\bpassword=)(\S+)")


def redact_dsn(text: str) -> str:
    """Return `text` with any PostgreSQL DSN password redacted.

    Handles both URI-style DSNs (postgresql://user:pass@host/db) and
    libpq keyword/value DSNs (host=... password=... dbname=...). Text
    with no recognizable password is returned unchanged. Usernames are
    intentionally left visible -- only the password is sensitive.
    """
    redacted = _URI_PASSWORD_PATTERN.sub(rf"\1{_REDACTED}\3", text)
    redacted = _KEYWORD_PASSWORD_PATTERN.sub(rf"\1{_REDACTED}", redacted)
    return redacted


def _redact_value(value: Any) -> Any:
    """Redact a single log argument, leaving non-string values alone."""
    return redact_dsn(value) if isinstance(value, str) else value


def _redact_args(args: Any) -> Any:
    """Redact log record arguments without changing their container type.

    `logging` accepts either a tuple of positional arguments (for
    `%s`-style messages) or a single mapping (for `%(name)s`-style
    messages). Coercing the mapping into a tuple would turn it into a
    tuple of its *keys* and break formatting with "format requires a
    mapping", so the mapping shape is preserved here.
    """
    if isinstance(args, dict):
        return {key: _redact_value(value) for key, value in args.items()}
    if isinstance(args, tuple):
        return tuple(_redact_value(value) for value in args)
    return args


class CredentialRedactionFilter(logging.Filter):
    """A logging filter that redacts DSN passwords from every record.

    Attached to the handler in `logging_config.configure_logging()` so
    that no code path -- present or future, and regardless of log
    level or output format -- can accidentally leak a password into
    log output.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # str() rather than an isinstance check: a non-string msg (an
        # exception object, say) can still stringify to something
        # containing a DSN, and logging stringifies it anyway.
        record.msg = redact_dsn(str(record.msg))
        if record.args:
            record.args = _redact_args(record.args)
        return True