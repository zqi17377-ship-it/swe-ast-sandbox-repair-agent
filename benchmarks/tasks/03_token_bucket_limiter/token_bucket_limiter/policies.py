"""Multi-tenant rate-limit tier definitions and client resolution policies."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RateTier:
    """Named burst capacity and steady-state refill specification."""

    name: str
    burst_capacity: float
    sustained_rps: float
    priority: int = 0


class TierRegistry:
    """Registry mapping subscription plan names to `RateTier` configurations."""

    def __init__(self) -> None:
        self._tiers: dict[str, RateTier] = {
            "free": RateTier("free", burst_capacity=10.0, sustained_rps=2.0, priority=1),
            "pro": RateTier("pro", burst_capacity=100.0, sustained_rps=25.0, priority=2),
            "enterprise": RateTier(
                "enterprise", burst_capacity=1000.0, sustained_rps=250.0, priority=3
            ),
        }

    def register(self, tier: RateTier) -> None:
        """Add or replace a named rate tier."""
        if tier.burst_capacity < tier.sustained_rps * 0.1:
            raise ValueError("burst_capacity is unrealistically small for sustained_rps.")
        self._tiers[tier.name] = tier

    def resolve(self, plan_name: str) -> RateTier:
        """Look up a tier by plan name, falling back to 'free' when unknown."""
        key = plan_name.strip().lower()
        return self._tiers.get(key, self._tiers["free"])

    def list_tiers(self) -> list[RateTier]:
        """Return registered tiers ordered by ascending priority."""
        return sorted(self._tiers.values(), key=lambda t: (t.priority, t.name))
