"""Deterministic clock utilities for rate-limiter testing and instrumentation."""

from __future__ import annotations

import time


class ManualClock:
    """Controllable clock supporting explicit advances and NTP skew injection."""

    def __init__(self, start_time: float = 0.0) -> None:
        self._current = float(start_time)

    def __call__(self) -> float:
        return self._current

    def advance(self, delta_sec: float) -> float:
        self._current += delta_sec
        return self._current

    def set_time(self, timestamp: float) -> None:
        self._current = float(timestamp)


def system_monotonic_seconds() -> float:
    """Return monotonic host timestamp in seconds."""
    return time.monotonic()
