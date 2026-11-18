"""Gap discovery and pairwise intersection queries over sorted intervals."""

from __future__ import annotations

from interval_merger.models import Interval


def find_free_gaps(
    busy: list[Interval], window_start: int, window_end: int
) -> list[Interval]:
    """Return unallocated `[start, end)` gaps inside `[window_start, window_end)`."""
    if window_start >= window_end:
        return []
    ordered = sorted(busy, key=lambda iv: (iv.start, iv.end))
    gaps: list[Interval] = []
    cursor = window_start
    for iv in ordered:
        if iv.end <= cursor:
            continue
        if iv.start > cursor:
            gap_end = min(window_end, iv.start)
            if gap_end > cursor:
                gaps.append(Interval(cursor, gap_end))
        cursor = max(cursor, iv.end)
        if cursor >= window_end:
            break
    if cursor < window_end:
        gaps.append(Interval(cursor, window_end))
    return gaps


def intersect_two_schedules(
    left: list[Interval], right: list[Interval]
) -> list[Interval]:
    """Compute pairwise overlapping sub-intervals between two sorted lists."""
    a = sorted(left, key=lambda iv: (iv.start, iv.end))
    b = sorted(right, key=lambda iv: (iv.start, iv.end))
    i = j = 0
    out: list[Interval] = []
    while i < len(a) and j < len(b):
        lo = max(a[i].start, b[j].start)
        hi = min(a[i].end, b[j].end)
        if lo < hi:
            out.append(Interval(lo, hi))
        if a[i].end < b[j].end:
            i += 1
        else:
            j += 1
    return out
