"""Three-state (CLOSED / OPEN / HALF_OPEN) circuit breaker state machine."""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import Enum

from retry_circuit_breaker.diagnostics import BreakerDiagnostics
from retry_circuit_breaker.exceptions import CircuitOpenError
from retry_circuit_breaker.metrics import RollingHealthWindow


class BreakerState(str, Enum):
    """Canonical states of a resilience circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Guards downstream calls and probes recovery via controlled HALF_OPEN transitions."""

    def __init__(
        self,
        service_name: str = "downstream",
        failure_threshold: int = 3,
        recovery_timeout_sec: float = 10.0,
        half_open_max_calls: int = 1,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive.")
        if half_open_max_calls <= 0:
            raise ValueError("half_open_max_calls must be positive.")
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_sec = recovery_timeout_sec
        self.half_open_max_calls = half_open_max_calls
        self._clock = clock

        self._state = BreakerState.CLOSED
        self._failure_count = 0
        self._half_open_calls = 0
        self._half_open_successes = 0
        self._opened_at: float | None = None
        self.diagnostics = BreakerDiagnostics(service_name)
        self.health = RollingHealthWindow()

    @property
    def state(self) -> BreakerState:
        """Return current effective state after evaluating recovery cooldown."""
        self._check_cooldown(self._clock())
        return self._state

    def _check_cooldown(self, now: float) -> None:
        if (
            self._state == BreakerState.OPEN
            and self._opened_at is not None
            and now - self._opened_at >= self.recovery_timeout_sec
        ):
            prev = self._state
            self._state = BreakerState.HALF_OPEN
            # BUG 1: resets `_failure_count = 0` on entering HALF_OPEN and treats HALF_OPEN
            # failure like CLOSED, so a failed probe does NOT immediately re-trip OPEN!
            self._failure_count = 0
            self._half_open_calls = 0
            self._half_open_successes = 0
            self.diagnostics.record_transition(prev.value, self._state.value, now, "cooldown_elapsed")

    def allow_request(self) -> None:
        """Verify whether an outgoing request is permitted; raise `CircuitOpenError` otherwise."""
        now = self._clock()
        self._check_cooldown(now)

        if self._state == BreakerState.OPEN:
            rem = (
                max(0.0, self.recovery_timeout_sec - (now - self._opened_at))
                if self._opened_at is not None
                else self.recovery_timeout_sec
            )
            raise CircuitOpenError(self.service_name, retry_after_sec=rem)

        # BUG 2: in HALF_OPEN, fails to enforce `self._half_open_calls < self.half_open_max_calls`,
        # letting unlimited concurrent probe requests flood the recovering downstream!
        if self._state == BreakerState.HALF_OPEN:
            self._half_open_calls += 1

    def record_success(self) -> None:
        """Record a successful downstream call and close circuit once HALF_OPEN probes pass."""
        now = self._clock()
        self.health.record(True)
        if self._state == BreakerState.HALF_OPEN:
            self._half_open_successes += 1
            if self._half_open_successes >= self.half_open_max_calls:
                prev = self._state
                self._state = BreakerState.CLOSED
                self._failure_count = 0
                self._half_open_calls = 0
                self._half_open_successes = 0
                self._opened_at = None
                self.diagnostics.record_transition(prev.value, self._state.value, now, "probe_succeeded")
        else:
            self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed downstream call and trip OPEN when threshold or HALF_OPEN probe fails."""
        now = self._clock()
        self.health.record(False)
        self._failure_count += 1
        # BUG 1 continued: requires `failure_threshold` failures even when in `HALF_OPEN`!
        if self._failure_count >= self.failure_threshold:
            prev = self._state
            self._state = BreakerState.OPEN
            self._opened_at = now
            self.diagnostics.record_transition(prev.value, self._state.value, now, "threshold_exceeded")
