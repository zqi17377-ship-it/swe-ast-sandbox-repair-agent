"""Hit/miss telemetry counters and rolling window statistics for cache instances."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class CacheTelemetry:
    """Tracks lifetime and rolling hit/miss/eviction counters."""

    window_size: int = 100
    hits: int = 0
    misses: int = 0
    expired_removals: int = 0
    capacity_evictions: int = 0
    writes: int = 0
    _recent_outcomes: deque[bool] = field(default_factory=deque)

    def record_hit(self) -> None:
        """Record a cache read hit."""
        self.hits += 1
        self._push_outcome(True)

    def record_miss(self, expired: bool = False) -> None:
        """Record a cache read miss and whether it was caused by TTL expiration."""
        self.misses += 1
        if expired:
            self.expired_removals += 1
        self._push_outcome(False)

    def record_write(self) -> None:
        """Record an insert or update operation."""
        self.writes += 1

    def record_capacity_eviction(self) -> None:
        """Record an LRU capacity eviction."""
        self.capacity_evictions += 1

    def _push_outcome(self, hit: bool) -> None:
        self._recent_outcomes.append(hit)
        while len(self._recent_outcomes) > self.window_size:
            self._recent_outcomes.popleft()

    @property
    def hit_rate(self) -> float:
        """Compute cumulative lifetime cache hit ratio."""
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return round(self.hits / total, 4)

    @property
    def rolling_hit_rate(self) -> float:
        """Compute hit ratio over the sliding outcome window."""
        if not self._recent_outcomes:
            return 0.0
        positives = sum(1 for item in self._recent_outcomes if item)
        return round(positives / len(self._recent_outcomes), 4)

    def snapshot(self) -> dict[str, float | int]:
        """Export metrics as a serializable dictionary."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "writes": self.writes,
            "expired_removals": self.expired_removals,
            "capacity_evictions": self.capacity_evictions,
            "hit_rate": self.hit_rate,
            "rolling_hit_rate": self.rolling_hit_rate,
        }
