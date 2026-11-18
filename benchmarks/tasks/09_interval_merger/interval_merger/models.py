"""Immutable numeric interval representation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Interval:
    """Numeric interval `[start, end)` or `[start, end]` with `start <= end`."""

    start: int
    end: int
    label: str = ""

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError(
                f"Interval start ({self.start}) must not exceed end ({self.end})."
            )

    @property
    def length(self) -> int:
        return self.end - self.start
