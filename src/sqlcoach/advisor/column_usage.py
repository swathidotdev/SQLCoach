"""Per-table column-usage extraction from a query's AST.

The index advisor needs to know, for each table a query touches, which
columns are used in equality filters, range filters, join conditions,
ORDER BY, and the SELECT list. Those facts come from the SQL itself
(its predicates), not from the execution plan -- the plan tells us a
scan is slow, the query tells us which columns to index.

Column-to-table attribution is deliberately conservative (precision
over recall, per the Sprint 7 design):

- A qualified column (``o.user_id``) is attributed via the query's
  alias map (``o`` -> ``orders``).
- An unqualified column (``user_id``) is attributed only when the query
  references exactly one table; in a multi-table query it is ambiguous
  without schema information, so it is skipped rather than guessed.

Extraction is best-effort and never raises: a query that fails to parse
yields no usage (and therefore no recommendations), rather than
aborting analysis of the rest of the workload.
"""

from __future__ import annotations

import logging
from typing import Callable, NamedTuple, Optional

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError as SqlglotParseError

from sqlcoach.parser.sql_ast_utils import DIALECT

logger = logging.getLogger(__name__)

_RANGE_OPS: tuple[type[exp.Expression], ...] = (exp.GT, exp.GTE, exp.LT, exp.LTE)


class ColumnUsage(NamedTuple):
    """How a single table's columns are used within one query.

    Every field lists distinct column names in first-seen order.

    Attributes:
        equality_filters: Columns compared for equality against a value
            (``col = 5``). The strongest single-column index candidates.
        range_filters: Columns compared with an inequality or BETWEEN
            against a value (``col > 5``). Index-usable, but should
            follow equality columns in a composite index.
        join_columns: Columns compared against another column
            (``a.x = b.y``), i.e. join keys.
        order_by_columns: Columns appearing in ORDER BY, in order.
        selected_columns: Columns appearing in the SELECT list.
        select_is_star: True if the query selects ``*`` (or ``t.*``),
            in which case the selected column set is unknown and
            covering-index analysis does not apply.
    """

    equality_filters: tuple[str, ...]
    range_filters: tuple[str, ...]
    join_columns: tuple[str, ...]
    order_by_columns: tuple[str, ...]
    selected_columns: tuple[str, ...]
    select_is_star: bool


class _OrderedSet:
    """A tiny insertion-ordered de-duplicating collector."""

    def __init__(self) -> None:
        self._items: list[str] = []
        self._seen: set[str] = set()

    def add(self, item: str) -> None:
        if item not in self._seen:
            self._seen.add(item)
            self._items.append(item)

    def frozen(self) -> tuple[str, ...]:
        return tuple(self._items)


class _TableUsageBuilder:
    """Mutable accumulator for one table's column usage."""

    def __init__(self) -> None:
        self.equality = _OrderedSet()
        self.range = _OrderedSet()
        self.join = _OrderedSet()
        self.order_by = _OrderedSet()
        self.selected = _OrderedSet()
        self.select_is_star = False

    def build(self) -> ColumnUsage:
        return ColumnUsage(
            equality_filters=self.equality.frozen(),
            range_filters=self.range.frozen(),
            join_columns=self.join.frozen(),
            order_by_columns=self.order_by.frozen(),
            selected_columns=self.selected.frozen(),
            select_is_star=self.select_is_star,
        )


class _Resolver:
    """Resolves a column expression to its owning table name."""

    def __init__(self, statement: exp.Expression) -> None:
        self._alias_to_table: dict[str, str] = {}
        table_names: list[str] = []
        for table in statement.find_all(exp.Table):
            name = table.name
            if not name:
                continue
            table_names.append(name)
            self._alias_to_table[name] = name
            alias = table.alias
            if alias:
                self._alias_to_table[alias] = name
        # Distinct table names; if exactly one, unqualified columns are
        # unambiguous and belong to it.
        self._distinct_tables = list(dict.fromkeys(table_names))

    def resolve(self, column: exp.Column) -> Optional[str]:
        qualifier = column.table
        if qualifier:
            return self._alias_to_table.get(qualifier, qualifier)
        if len(self._distinct_tables) == 1:
            return self._distinct_tables[0]
        return None  # unqualified in a multi-table query: ambiguous, skip


# A collector receives a resolved column and the shared builder registry.
_BuilderFor = Callable[[exp.Column], Optional[_TableUsageBuilder]]


def _is_top_level_star(projection: exp.Expression) -> bool:
    """True only for a whole-projection star (``*`` or ``t.*``).

    A star nested inside an expression -- notably ``COUNT(*)`` -- is not
    a select-star: it selects no named column, so it must not set the
    "select is star" flag (which would wrongly suppress covering-index
    analysis).
    """
    if isinstance(projection, exp.Star):
        return True
    return isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star)


def extract_column_usage(sql: str) -> dict[str, ColumnUsage]:
    """Extract per-table column usage from a SQL query.

    Args:
        sql: The query text.

    Returns:
        A mapping of table name to its ColumnUsage. Empty when the query
        cannot be parsed or references no tables.
    """
    try:
        statement = sqlglot.parse_one(sql, read=DIALECT)
    except SqlglotParseError:
        logger.debug("Could not parse query for column-usage extraction; skipping")
        return {}
    if statement is None:
        return {}

    resolver = _Resolver(statement)
    builders: dict[str, _TableUsageBuilder] = {}

    def builder_for(column: exp.Column) -> Optional[_TableUsageBuilder]:
        table = resolver.resolve(column)
        if table is None:
            return None
        return builders.setdefault(table, _TableUsageBuilder())

    _collect_predicates(statement, builder_for)
    _collect_order_by(statement, builder_for)
    _collect_selected(statement, builder_for, builders)

    return {table: b.build() for table, b in builders.items()}


def _predicate_scopes(statement: exp.Expression) -> list[exp.Expression]:
    """Return the AST subtrees where index-relevant predicates live:
    WHERE clauses and join ON conditions.
    """
    scopes: list[exp.Expression] = list(statement.find_all(exp.Where))
    for join in statement.find_all(exp.Join):
        on = join.args.get("on")
        if on is not None:
            scopes.append(on)
    return scopes


def _collect_predicates(statement: exp.Expression, builder_for: _BuilderFor) -> None:
    for scope in _predicate_scopes(statement):
        for eq in scope.find_all(exp.EQ):
            _classify_equality(eq, builder_for)
        for op in scope.find_all(*_RANGE_OPS):
            _classify_range(op, builder_for)
        for between in scope.find_all(exp.Between):
            _classify_between(between, builder_for)


def _classify_equality(eq: exp.EQ, builder_for: _BuilderFor) -> None:
    left, right = eq.this, eq.args.get("expression")
    left_col = isinstance(left, exp.Column)
    right_col = isinstance(right, exp.Column)
    if left_col and right_col:
        # column = column -> a join key on both sides.
        _add(left, builder_for, "join")
        _add(right, builder_for, "join")
    elif left_col:
        _add(left, builder_for, "equality")
    elif right_col:
        _add(right, builder_for, "equality")


def _classify_range(op: exp.Expression, builder_for: _BuilderFor) -> None:
    left, right = op.this, op.args.get("expression")
    left_col = isinstance(left, exp.Column)
    right_col = isinstance(right, exp.Column)
    # Only "column OP value" is a useful single-table range predicate;
    # a column-vs-column range (rare) isn't a helpful index candidate.
    if left_col and not right_col:
        _add(left, builder_for, "range")
    elif right_col and not left_col:
        _add(right, builder_for, "range")


def _classify_between(between: exp.Between, builder_for: _BuilderFor) -> None:
    target = between.this
    if isinstance(target, exp.Column):
        _add(target, builder_for, "range")


def _collect_order_by(statement: exp.Expression, builder_for: _BuilderFor) -> None:
    order = statement.find(exp.Order)
    if order is None:
        return
    for ordered in order.expressions:
        target = ordered.this
        if isinstance(target, exp.Column) and not isinstance(target.this, exp.Star):
            _add(target, builder_for, "order_by")


def _collect_selected(
    statement: exp.Expression,
    builder_for: _BuilderFor,
    builders: dict[str, _TableUsageBuilder],
) -> None:
    select = statement.find(exp.Select)
    if select is None:
        return
    for projection in select.expressions:
        if _is_top_level_star(projection):
            _mark_star(projection, builder_for, builders)
            continue
        # A nested star (e.g. COUNT(*)) is not a select-star and selects
        # no named column; only plain columns are collected here.
        for column in projection.find_all(exp.Column):
            if not isinstance(column.this, exp.Star):
                _add(column, builder_for, "selected")


def _mark_star(
    projection: exp.Expression,
    builder_for: _BuilderFor,
    builders: dict[str, _TableUsageBuilder],
) -> None:
    """Flag star selection. ``t.*`` marks table t; a bare ``*`` marks
    every table already known to the query (predicate/order collection
    runs first, so filtered tables exist by now).
    """
    if isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star):
        builder = builder_for(projection)
        if builder is not None:
            builder.select_is_star = True
        return
    for builder in builders.values():
        builder.select_is_star = True


def _add(column: exp.Column, builder_for: _BuilderFor, field: str) -> None:
    builder = builder_for(column)
    if builder is None:
        return
    getattr(builder, field).add(column.name)