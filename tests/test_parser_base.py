"""Unit tests for sqlcoach.parser.base."""

from __future__ import annotations

from pathlib import Path
from typing import Union

import pytest

from sqlcoach.models.query import Query, QuerySource
from sqlcoach.parser.base import Parser


class _StubParser:
    """A plain object that structurally satisfies the Parser protocol,
    without inheriting from it -- this is the point of using Protocol.
    """

    def parse(self, source: Union[str, Path]) -> list[Query]:
        return [Query(text="SELECT 1;", source=QuerySource.SQL_FILE)]


class _NotAParser:
    """An object that does not implement `parse` at all."""

    def load(self, source: str) -> list[Query]:
        return []


class TestProtocolConformance:
    def test_object_with_matching_parse_method_satisfies_protocol(self) -> None:
        assert isinstance(_StubParser(), Parser)

    def test_object_without_parse_method_does_not_satisfy_protocol(self) -> None:
        assert not isinstance(_NotAParser(), Parser)

    def test_protocol_cannot_be_instantiated_directly(self) -> None:
        with pytest.raises(TypeError):
            Parser()  # type: ignore[abstract]


class TestStubParserBehavior:
    def test_stub_parser_returns_query_objects(self) -> None:
        parser = _StubParser()
        results = parser.parse("queries.sql")
        assert len(results) == 1
        assert isinstance(results[0], Query)