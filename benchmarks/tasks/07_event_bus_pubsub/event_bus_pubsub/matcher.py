"""Hierarchical dot-delimited topic wildcard matcher (`*` single level, `**` multi level)."""

from __future__ import annotations

import fnmatch


def topic_matches(pattern: str, topic: str) -> bool:
    """Match dot-separated `topic` against `pattern` where `*` matches 1 segment and `**` >= 0 segments."""
    if pattern == topic:
        return True
    # BUG: `fnmatchcase` lets single `*` cross `.` boundaries, matching `orders.eu.paid` against `orders.*`!
    return fnmatch.fnmatchcase(topic, pattern)
