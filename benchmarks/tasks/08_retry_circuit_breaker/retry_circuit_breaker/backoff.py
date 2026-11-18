"""Exponential backoff with bounded cap and deterministic decorrelated jitter."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BackoffPolicy:
    """Parameters governing retry sleep schedules."""

    base_delay_sec: float = 0.25
    multiplier: float = 2.0
    max_delay_sec: float = 16.0
    max_attempts: int = 4


def compute_backoff_delay(
    attempt: int,
    policy: BackoffPolicy | None = None,
    jitter_ratio: float = 0.0,
) -> float:
    """Compute delay before `attempt` (1-indexed) clamped at `max_delay_sec`."""
    cfg = policy or BackoffPolicy()
    if attempt <= 0:
        return 0.0
    raw = cfg.base_delay_sec * (cfg.multiplier ** (attempt - 1))
    capped = min(cfg.max_delay_sec, raw)
    clamped_jitter = max(-0.5, min(0.5, jitter_ratio))
    return round(max(0.0, capped * (1.0 + clamped_jitter)), 6)


def total_retry_budget_sec(policy: BackoffPolicy) -> float:
    """Compute worst-case cumulative sleep time across all retry attempts."""
    return round(
        sum(compute_backoff_delay(i, policy) for i in range(1, policy.max_attempts)),
        6,
    )
