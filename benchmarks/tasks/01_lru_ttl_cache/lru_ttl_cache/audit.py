"""Structured audit log and eviction forensics for cache operations."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvictionEvent:
    """Immutable record describing why a cache key was removed."""

    key: str
    reason: str
    timestamp: float
    age_seconds: float
    access_count: int


@dataclass
class AuditTrail:
    """Ring-buffered audit log tracking cache evictions and expirations."""

    max_events: int = 256
    _events: list[EvictionEvent] = field(default_factory=list)

    def record(
        self,
        key: str,
        reason: str,
        timestamp: float,
        created_at: float,
        access_count: int,
    ) -> None:
        """Append an eviction event while enforcing ring capacity."""
        age = max(0.0, timestamp - created_at)
        event = EvictionEvent(
            key=key,
            reason=reason,
            timestamp=timestamp,
            age_seconds=round(age, 6),
            access_count=access_count,
        )
        self._events.append(event)
        if len(self._events) > self.max_events:
            overflow = len(self._events) - self.max_events
            del self._events[:overflow]

    def events_by_reason(self, reason: str) -> list[EvictionEvent]:
        """Filter recorded events matching a specific eviction reason."""
        return [ev for ev in self._events if ev.reason == reason]

    def reason_counts(self) -> dict[str, int]:
        """Aggregate total eviction counts grouped by reason."""
        counts: Counter[str] = Counter(ev.reason for ev in self._events)
        return dict(counts)

    def latest(self, limit: int = 10) -> list[EvictionEvent]:
        """Return the most recent `limit` eviction events."""
        if limit <= 0:
            return []
        return list(self._events[-limit:])

    def clear(self) -> None:
        """Reset all stored audit records."""
        self._events.clear()


def summarize_evictions(trail: AuditTrail) -> str:
    """Format a human-readable summary report of recorded evictions."""
    counts = trail.reason_counts()
    if not counts:
        return "No cache evictions recorded."
    parts = [f"{reason}={count}" for reason, count in sorted(counts.items())]
    recent = trail.latest(3)
    tail_keys = ", ".join(f"{ev.key}({ev.reason})" for ev in recent)
    return f"Evictions[{', '.join(parts)}] | Recent: {tail_keys}"
