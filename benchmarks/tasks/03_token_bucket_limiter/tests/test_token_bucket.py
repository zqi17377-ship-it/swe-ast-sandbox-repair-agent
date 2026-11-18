"""Tests for TokenBucket burst cap clamping, retry-after math, clock skew, and cost validation."""

from __future__ import annotations

import pytest

from token_bucket_limiter import TokenBucket
from token_bucket_limiter.clock import ManualClock


def test_steady_consume_and_retry_after() -> None:
    clock = ManualClock(100.0)
    bucket = TokenBucket(capacity=10.0, refill_rate=2.0, clock=clock)

    res1 = bucket.consume(8.0)
    assert res1.allowed is True
    assert res1.remaining_tokens == pytest.approx(2.0)

    res2 = bucket.consume(5.0)
    assert res2.allowed is False
    assert res2.retry_after_sec == pytest.approx(1.5)


def test_idle_refill_never_exceeds_burst_capacity() -> None:
    clock = ManualClock(0.0)
    bucket = TokenBucket(capacity=10.0, refill_rate=5.0, clock=clock, initial_tokens=4.0)

    clock.advance(60.0)  # 300 potential tokens, must cap at capacity=10.0!
    assert bucket.available_tokens == pytest.approx(10.0)

    res = bucket.consume(10.0)
    assert res.allowed is True
    assert res.remaining_tokens == pytest.approx(0.0)


def test_backward_clock_skew_does_not_drain_tokens() -> None:
    clock = ManualClock(50.0)
    bucket = TokenBucket(capacity=10.0, refill_rate=2.0, clock=clock, initial_tokens=6.0)

    # Out-of-order caller supplies slightly earlier timestamp 48.0: must NOT subtract 4 tokens!
    res = bucket.consume(2.0, now=48.0)
    assert res.allowed is True
    assert res.remaining_tokens == pytest.approx(4.0)

    # Subsequent forward timestamp 51.0 should refill from 50.0 (1s * 2.0 = +2.0 -> 6.0)
    assert bucket.available_tokens == pytest.approx(4.0)
    clock.set_time(51.0)
    assert bucket.available_tokens == pytest.approx(6.0)


def test_non_positive_cost_raises_value_error() -> None:
    bucket = TokenBucket(capacity=10.0, refill_rate=1.0)
    with pytest.raises(ValueError):
        bucket.consume(0.0)
    with pytest.raises(ValueError):
        bucket.consume(-3.0)
