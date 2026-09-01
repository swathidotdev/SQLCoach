"""Unit tests for sqlcoach.redaction."""

from __future__ import annotations

import logging

import pytest

from sqlcoach.redaction import CredentialRedactionFilter, redact_dsn


class TestRedactDsnUriStyle:
    def test_redacts_password_in_uri_dsn(self) -> None:
        result = redact_dsn("postgresql://alice:s3cr3t@localhost:5432/mydb")
        assert "s3cr3t" not in result
        assert "alice" in result
        assert "***REDACTED***" in result

    def test_leaves_user_only_uri_unchanged(self) -> None:
        dsn = "postgresql://alice@localhost:5432/mydb"
        assert redact_dsn(dsn) == dsn

    def test_leaves_text_without_a_dsn_unchanged(self) -> None:
        text = "Connected to mydb successfully"
        assert redact_dsn(text) == text


class TestRedactDsnKeywordStyle:
    def test_redacts_password_keyword(self) -> None:
        result = redact_dsn("host=localhost password=s3cr3t dbname=mydb")
        assert "s3cr3t" not in result
        assert "host=localhost" in result
        assert "dbname=mydb" in result

    def test_is_case_insensitive(self) -> None:
        result = redact_dsn("host=localhost PASSWORD=s3cr3t")
        assert "s3cr3t" not in result


class TestRedactDsnMixedContent:
    def test_redacts_within_a_larger_log_message(self) -> None:
        message = "Failed to connect using postgresql://alice:s3cr3t@localhost/mydb: timeout"
        result = redact_dsn(message)
        assert "s3cr3t" not in result
        assert "timeout" in result
        assert "alice" in result


class TestCredentialRedactionFilter:
    def _make_record(self, msg: str, args: tuple = ()) -> logging.LogRecord:
        return logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname=__file__,
            lineno=1,
            msg=msg,
            args=args,
            exc_info=None,
        )

    def test_redacts_msg_in_place(self) -> None:
        record = self._make_record("DSN: postgresql://alice:s3cr3t@localhost/mydb")
        CredentialRedactionFilter().filter(record)
        assert "s3cr3t" not in str(record.msg)

    def test_redacts_string_args_in_place(self) -> None:
        record = self._make_record(
            "Connecting with %s", args=("postgresql://alice:s3cr3t@localhost/mydb",)
        )
        CredentialRedactionFilter().filter(record)
        assert all("s3cr3t" not in arg for arg in record.args if isinstance(arg, str))

    def test_leaves_non_string_args_untouched(self) -> None:
        record = self._make_record("Retry attempt %d", args=(3,))
        CredentialRedactionFilter().filter(record)
        assert record.args == (3,)

    def test_filter_always_returns_true(self) -> None:
        record = self._make_record("plain message")
        assert CredentialRedactionFilter().filter(record) is True



class TestMappingStyleLogArguments:
    """`logging` accepts a single mapping for %(name)s-style messages.
    Coercing it to a tuple yields a tuple of keys and breaks formatting.
    """

    def test_mapping_args_stay_a_mapping_and_are_redacted(self) -> None:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="p",
            lineno=1,
            msg="connecting to %(dsn)s as %(user)s",
            args={"dsn": "postgresql://alice:s3cret@localhost/mydb", "user": "alice"},
            exc_info=None,
        )

        CredentialRedactionFilter().filter(record)

        assert isinstance(record.args, dict)
        message = record.getMessage()
        assert "s3cret" not in message
        assert "***REDACTED***" in message
        assert "alice" in message

    def test_tuple_args_still_work(self) -> None:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="p",
            lineno=1,
            msg="connecting to %s",
            args=("postgresql://alice:s3cret@localhost/mydb",),
            exc_info=None,
        )

        CredentialRedactionFilter().filter(record)

        assert "s3cret" not in record.getMessage()