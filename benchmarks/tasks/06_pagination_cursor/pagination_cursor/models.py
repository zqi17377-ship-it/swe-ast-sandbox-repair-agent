"""Domain models for keyset-paginated items and page envelopes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RecordItem:
    """Sortable domain item uniquely identified by `(sort_value, item_id)`."""

    item_id: str
    sort_value: int
    payload: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()

    @property
    def sort_tuple(self) -> tuple[int, str]:
        return (self.sort_value, self.item_id)


@dataclass(frozen=True)
class PageResult:
    """Single keyset page response with opaque continuation cursor."""

    items: list[RecordItem]
    next_cursor: str | None
    has_more: bool
