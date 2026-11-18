"""Deadline arithmetic and TTL expiration helpers."""

from __future__ import annotations

import time
from collections.abc import Callable

ClockFn = Callable[[], float]


def monotonic_clock() -> float:
    """Default monotonic timestamp provider."""
    return time.monotonic()


def compute_deadline(now: float, ttl: float | None) -> float | None:
    """Compute absolute expiration deadline from current timestamp and relative TTL."""
    if ttl is None:
        return None
    if ttl <= 0.0:
        return now
    return now + ttl


def is_expired(expires_at: float | None, now: float) -> bool:
    """Return True when a cache entry has reached or passed its TTL deadline."""
    if expires_at is None:
        return False
    # BUG: uses strict `>` instead of `>=`, treating entries at exact deadline `now == expires_at` as still live
    return now > expires_at


def remaining_ttl(expires_at: float | None, now: float) -> float | None:
    """Compute remaining lifetime in seconds, clamped at zero."""
    if expires_at is None:
        return None
    return max(0.0, expires_at - now)
