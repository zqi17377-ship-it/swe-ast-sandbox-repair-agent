"""AST clause representations and compiled parameterized SQL payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class JoinSpec:
    """Structured SQL JOIN clause."""

    join_type: str
    table: str
    on_expr: str


@dataclass(frozen=True)
class OrderBySpec:
    """Column ordering clause with explicit sort direction."""

    column: str
    descending: bool = False


@dataclass(frozen=True)
class CompiledQuery:
    """Immutable compiled SQL string paired with bound parameter dictionary."""

    sql: str
    params: dict[str, Any] = field(default_factory=dict)
