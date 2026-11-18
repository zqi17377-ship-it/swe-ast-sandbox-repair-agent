"""Tests for CircuitBreaker HALF_OPEN single-failure immediate re-open and probe quota cap."""

from __future__ import annotations

import pytest

from retry_circuit_breaker import BreakerState, CircuitBreaker, CircuitOpenError


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, delta: float) -> None:
        self.now += delta


def test_trips_open_after_reaching_failure_threshold() -> None:
    clock = FakeClock(10.0)
    cb = CircuitBreaker("payments", failure_threshold=3, recovery_timeout_sec=15.0, clock=clock)

    for _ in range(3):
        cb.allow_request()
        cb.record_failure()

    assert cb.state == BreakerState.OPEN
    with pytest.raises(CircuitOpenError):
        cb.allow_request()


def test_half_open_single_probe_failure_immediately_reopens_circuit() -> None:
    clock = FakeClock(0.0)
    cb = CircuitBreaker("payments", failure_threshold=3, recovery_timeout_sec=10.0, clock=clock)

    for _ in range(3):
        cb.allow_request()
        cb.record_failure()
    assert cb.state == BreakerState.OPEN

    clock.advance(10.0)
    assert cb.state == BreakerState.HALF_OPEN

    cb.allow_request()
    cb.record_failure()
    # A single failed probe in HALF_OPEN must immediately re-open the circuit!
    assert cb.state == BreakerState.OPEN
    with pytest.raises(CircuitOpenError):
        cb.allow_request()


def test_half_open_enforces_max_concurrent_probe_calls() -> None:
    clock = FakeClock(0.0)
    cb = CircuitBreaker(
        "inventory",
        failure_threshold=2,
        recovery_timeout_sec=5.0,
        half_open_max_calls=2,
        clock=clock,
    )
    cb.allow_request()
    cb.record_failure()
    cb.allow_request()
    cb.record_failure()
    assert cb.state == BreakerState.OPEN

    clock.advance(5.0)
    cb.allow_request()  # Probe 1 allowed
    cb.allow_request()  # Probe 2 allowed
    with pytest.raises(CircuitOpenError):
        cb.allow_request()  # Probe 3 must be rejected while in HALF_OPEN!

    cb.record_success()
    cb.record_success()
    assert cb.state == BreakerState.CLOSED
