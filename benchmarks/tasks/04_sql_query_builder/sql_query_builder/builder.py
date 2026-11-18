"""Fluent SELECT query builder with named parameter binding."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sql_query_builder.ast_nodes import CompiledQuery, JoinSpec, OrderBySpec
from sql_query_builder.dialects import DialectConfig, validate_identifier


class SelectQueryBuilder:
    """Builds safe parameterized SQL SELECT statements without string-interpolation injection."""

    def __init__(
        self,
        table: str,
        columns: Sequence[str] = ("*",),
        dialect: DialectConfig | None = None,
    ) -> None:
        self.dialect = dialect or DialectConfig()
        self.table = validate_identifier(table)
        self.columns = [
            "*" if col.strip() == "*" else validate_identifier(col) for col in columns
        ]
        self._joins: list[JoinSpec] = []
        self._where_clauses: list[str] = []
        self._params: dict[str, Any] = {}
        self._param_seq: int = 0
        self._order_by: list[OrderBySpec] = []
        self._limit: int | None = None
        self._offset: int | None = None

    def _alloc_param(self, prefix: str, value: Any) -> str:
        name = f"{prefix}_{self._param_seq}"
        self._param_seq += 1
        self._params[name] = value
        return f":{name}"

    def join(self, table: str, on_expr: str, join_type: str = "INNER") -> SelectQueryBuilder:
        """Append a SQL JOIN clause."""
        norm_type = join_type.strip().upper()
        if norm_type not in {"INNER", "LEFT", "RIGHT"}:
            raise ValueError(f"Unsupported join type: {join_type}")
        self._joins.append(JoinSpec(norm_type, validate_identifier(table), on_expr))
        return self

    def where_eq(self, column: str, value: Any) -> SelectQueryBuilder:
        """Append an equality predicate (`col = :p_N` or `col IS NULL`)."""
        col = validate_identifier(column)
        if value is None:
            self._where_clauses.append(f"{col} IS NULL")
        else:
            ph = self._alloc_param("eq", value)
            self._where_clauses.append(f"{col} = {ph}")
        return self

    def where_in(self, column: str, values: Sequence[Any]) -> SelectQueryBuilder:
        """Append a membership predicate `col IN (:in_0, :in_1, ...)`."""
        col = validate_identifier(column)
        # BUG 1: resets index `i` from 0 on each call, colliding `:in_0` across multiple where_in() calls!
        # BUG 2: empty `values` emits invalid SQL `col IN ()` instead of constant `1 = 0`!
        placeholders: list[str] = []
        for i, val in enumerate(values):
            key = f"in_{i}"
            self._params[key] = val
            placeholders.append(f":{key}")
        self._where_clauses.append(f"{col} IN ({', '.join(placeholders)})")
        return self

    def where_not_in(self, column: str, values: Sequence[Any]) -> SelectQueryBuilder:
        """Append a negated membership predicate `col NOT IN (...)`."""
        col = validate_identifier(column)
        # Same parameter-collision & empty-list (`1 = 1`) bug!
        placeholders: list[str] = []
        for i, val in enumerate(values):
            key = f"nin_{i}"
            self._params[key] = val
            placeholders.append(f":{key}")
        self._where_clauses.append(f"{col} NOT IN ({', '.join(placeholders)})")
        return self

    def order_by(self, column: str, descending: bool = False) -> SelectQueryBuilder:
        """Append an ORDER BY sort specification."""
        self._order_by.append(OrderBySpec(validate_identifier(column), descending))
        return self

    def limit(self, count: int, offset: int | None = None) -> SelectQueryBuilder:
        """Configure LIMIT and optional OFFSET pagination."""
        if count < 0:
            raise ValueError("LIMIT must be non-negative.")
        self._limit = count
        if offset is not None:
            if offset < 0:
                raise ValueError("OFFSET must be non-negative.")
            self._offset = offset
        return self

    def build(self) -> CompiledQuery:
        """Compile clauses into a parameterized SQL statement."""
        cols_sql = ", ".join(self.columns)
        parts = [f"SELECT {cols_sql} FROM {self.table}"]
        for j in self._joins:
            parts.append(f"{j.join_type} JOIN {j.table} ON {j.on_expr}")
        if self._where_clauses:
            parts.append("WHERE " + " AND ".join(self._where_clauses))
        if self._order_by:
            ord_sql = ", ".join(
                f"{o.column} {'DESC' if o.descending else 'ASC'}"
                for o in self._order_by
            )
            parts.append(f"ORDER BY {ord_sql}")
        if self._limit is not None:
            parts.append(f"LIMIT {self._limit}")
        if self._offset is not None:
            parts.append(f"OFFSET {self._offset}")
        return CompiledQuery(sql=" ".join(parts), params=dict(self._params))
