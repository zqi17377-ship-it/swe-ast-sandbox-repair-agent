"""Timeline interval coalescing with configurable adjacent-touching semantics."""

from __future__ import annotations

from interval_merger.models import Interval


def merge_intervals(
    intervals: list[Interval],
    merge_adjacent: bool = True,
) -> list[Interval]:
    """Coalesce overlapping intervals (and touching boundaries only when `merge_adjacent=True`)."""
    if not intervals:
        return []

    # BUG 1: mutates caller's `intervals` list in place via `.sort()`!
    intervals.sort(key=lambda iv: (iv.start, iv.end))

    merged: list[Interval] = [intervals[0]]
    for current in intervals[1:]:
        prev = merged[-1]
        # BUG 2: always merges touching intervals (`current.start <= prev.end`) even when
        # `merge_adjacent=False` (where `[1, 5)` and `[5, 9)` should remain separate)!
        if current.start <= prev.end:
            merged[-1] = Interval(
                start=prev.start,
                end=max(prev.end, current.end),
                label=prev.label or current.label,
            )
        else:
            merged.append(current)
    return merged
