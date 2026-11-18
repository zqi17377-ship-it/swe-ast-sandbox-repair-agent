"""String parsing and compact range formatting utilities for intervals."""

from __future__ import annotations

from interval_merger.models import Interval


def parse_interval_token(token: str) -> Interval:
    """Parse `'10..25'` or `'[10, 25)'` into an `Interval`."""
    cleaned = token.strip().strip("[]()")
    if ".." in cleaned:
        left, right = cleaned.split("..", 1)
    elif "," in cleaned:
        left, right = cleaned.split(",", 1)
    else:
        raise ValueError(f"Unrecognized interval syntax: {token!r}")
    return Interval(int(left.strip()), int(right.strip()))


def format_interval_timeline(intervals: list[Interval], inclusive: bool = False) -> str:
    """Format intervals using mathematical bracket notation."""
    right_br = "]" if inclusive else ")"
    return ", ".join(f"[{iv.start}, {iv.end}{right_br}" for iv in intervals)
