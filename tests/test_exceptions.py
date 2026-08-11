"""Unit tests for sqlcoach.exceptions."""

from __future__ import annotations

import pytest

from sqlcoach.exceptions import (
    ConfigError,
    DatabaseConnectionError,
    ParsingError,
    SQLCoachError,
    ValidationError,
)

ALL_SUBCLASSES: list[type[SQLCoachError]] = [
    ConfigError,
    ValidationError,
    ParsingError,
    DatabaseConnectionError,
]


class TestSQLCoachErrorBase:
    def test_is_an_exception(self) -> None:
        assert issubclass(SQLCoachError, Exception)

    def test_stores_message(self) -> None:
        error = SQLCoachError("something went wrong")
        assert error.message == "something went wrong"
        assert str(error) == "something went wrong"

    def test_details_default_to_empty_dict(self) -> None:
        error = SQLCoachError("boom")
        assert error.details == {}

    def test_str_renders_details_when_present(self) -> None:
        error = SQLCoachError("invalid value", details={"field": "port", "value": -1})
        rendered = str(error)
        assert rendered.startswith("invalid value (")
        assert "field='port'" in rendered
        assert "value=-1" in rendered

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(SQLCoachError):
            raise SQLCoachError("failure")


@pytest.mark.parametrize("exception_class", ALL_SUBCLASSES)
class TestSubclasses:
    def test_is_subclass_of_sqlcoach_error(self, exception_class: type[SQLCoachError]) -> None:
        assert issubclass(exception_class, SQLCoachError)

    def test_can_be_caught_as_base_class(self, exception_class: type[SQLCoachError]) -> None:
        with pytest.raises(SQLCoachError):
            raise exception_class("domain-specific failure")

    def test_carries_its_own_message_and_details(
        self, exception_class: type[SQLCoachError]
    ) -> None:
        error = exception_class("specific problem", details={"key": "value"})
        assert error.message == "specific problem"
        assert error.details == {"key": "value"}


class TestHierarchyIsFlat:
    """Guards against future edits accidentally nesting subclasses,
    which would break the Open/Closed guarantee in NFR-1.7.
    """

    def test_subclasses_do_not_inherit_from_each_other(self) -> None:
        for cls_a in ALL_SUBCLASSES:
            for cls_b in ALL_SUBCLASSES:
                if cls_a is not cls_b:
                    assert not issubclass(cls_a, cls_b)
