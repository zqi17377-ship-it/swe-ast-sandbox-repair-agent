"""Coverage density and fragmentation metrics over interval timelines."""

from __future__ import annotations

from dataclasses import dataclass

from interval_merger.models import Interval


@dataclass(frozen=True)
class CoverageSummary:
    """Summary statistics across a set of timeline intervals."""

    span_start: int
    span_end: int
    covered_length: int
    gap_length: int
    density: float


def summarize_coverage(intervals: list[Interval]) -> CoverageSummary:
    """Compute covered duration, gap duration, and utilization ratio."""
    non_empty = [iv for iv in intervals if iv.length > 0]
    if not non_empty:
        return CoverageSummary(0, 0, 0, 0, 0.0)

    ordered = sorted(non_empty, key=lambda iv: (iv.start, iv.end))
    span_start = ordered[0].start
    span_end = max(iv.end for iv in ordered)
    total_span = span_end - span_start
    if total_span <= 0:
        return CoverageSummary(span_start, span_end, 0, 0, 0.0)

    cur_s, cur_e = ordered[0].start, ordered[0].end
    covered = 0
    for iv in ordered[1:]:
        if iv.start <= cur_e:
            cur_e = max(cur_e, iv.end)
        else:
            covered += cur_e - cur_s
            cur_s, cur_e = iv.start, iv.end
    covered += cur_e - cur_s
    gaps = max(0, total_span - covered)
    return CoverageSummary(
        span_start=span_start,
        span_end=span_end,
        covered_length=covered,
        gap_length=gaps,
        density=round(covered / total_span, 4),
    )
