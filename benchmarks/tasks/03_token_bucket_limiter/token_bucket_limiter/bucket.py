"""Floating-point token bucket rate limiter with retry-after calculation."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ConsumeResult:
    """Outcome of attempting to acquire tokens from a bucket."""

    allowed: bool
    remaining_tokens: float
    retry_after_sec: float


class TokenBucket:
    """Rate limiter replenishing continuously at `refill_rate` tokens/sec up to `capacity`."""

    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        clock: Callable[[], float] = time.monotonic,
        initial_tokens: float | None = None,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive.")
        if refill_rate <= 0:
            raise ValueError("refill_rate must be positive.")
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        self._clock = clock
        self._tokens = (
            float(capacity)
            if initial_tokens is None
            else min(float(capacity), max(0.0, float(initial_tokens)))
        )
        self._last_refill = self._clock()

    @property
    def available_tokens(self) -> float:
        """Peek current token balance after applying elapsed refill."""
        self._refill(self._clock())
        return round(self._tokens, 6)

    def _refill(self, now: float) -> None:
        """Replenish tokens based on elapsed time since last refill."""
        # BUG 1: does not clamp `self._tokens` to `self.capacity` burst limit!
        # BUG 2: does not guard against backward clock skew (`now < self._last_refill`), draining tokens!
        elapsed = now - self._last_refill
        self._tokens = self._tokens + elapsed * self.refill_rate
        self._last_refill = now

    def consume(self, cost: float = 1.0, now: float | None = None) -> ConsumeResult:
        """Attempt to consume `cost` tokens atomically."""
        # BUG 3: missing validation for non-positive cost (`cost <= 0`)!
        ts = self._clock() if now is None else now
        self._refill(ts)

        if cost > self.capacity:
            return ConsumeResult(
                allowed=False,
                remaining_tokens=round(self._tokens, 6),
                retry_after_sec=float("inf"),
            )

        if self._tokens + 1e-9 >= cost:
            self._tokens = max(0.0, self._tokens - cost)
            return ConsumeResult(
                allowed=True,
                remaining_tokens=round(self._tokens, 6),
                retry_after_sec=0.0,
            )

        deficit = cost - self._tokens
        wait_sec = deficit / self.refill_rate
        return ConsumeResult(
            allowed=False,
            remaining_tokens=round(self._tokens, 6),
            retry_after_sec=round(wait_sec, 6),
        )
