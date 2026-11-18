"""Underlying storage slots backing root singletons and per-scope instances."""

from __future__ import annotations

from typing import Any


class InstanceBank:
    """Holds shared root map alongside context-local slot dictionary."""

    def __init__(
        self,
        root_cells: dict[str, Any] | None = None,
        local_slots: dict[str, Any] | None = None,
    ) -> None:
        self._root_cells: dict[str, Any] = root_cells if root_cells is not None else {}
        self._local_slots: dict[str, Any] = local_slots if local_slots is not None else {}

    def has_root(self, key: str) -> bool:
        return key in self._root_cells

    def read_root(self, key: str) -> Any:
        return self._root_cells[key]

    def write_root(self, key: str, val: Any) -> None:
        self._root_cells[key] = val

    def has_slot(self, key: str) -> bool:
        return key in self._local_slots

    def read_slot(self, key: str) -> Any:
        return self._local_slots[key]

    def write_slot(self, key: str, val: Any) -> None:
        self._local_slots[key] = val

    def _derive_standard_bank(self) -> InstanceBank:
        """Duplicate backing dictionaries for secondary tier."""
        return InstanceBank(
            root_cells=dict(self._root_cells),
            local_slots=dict(self._local_slots),
        )
