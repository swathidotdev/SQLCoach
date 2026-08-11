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


class CredentialRedactionFilter(logging.Filter):
    """A logging filter that redacts DSN passwords from every record.

    Attached to the handler in `logging_config.configure_logging()` so
    that no code path -- present or future, and regardless of log
    level or output format -- can accidentally leak a password into
    log output.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_dsn(str(record.msg))
        if record.args:
            record.args = tuple(
                redact_dsn(arg) if isinstance(arg, str) else arg for arg in record.args
            )
        return True