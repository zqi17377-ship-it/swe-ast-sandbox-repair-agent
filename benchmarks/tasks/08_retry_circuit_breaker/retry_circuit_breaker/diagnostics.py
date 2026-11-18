"""Audit log of circuit breaker state transitions for observability dashboards."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StateTransitionEvent:
    """Single state transition edge recorded by a circuit breaker."""

    service_name: str
    from_state: str
    to_state: str
    timestamp: float
    reason: str


@dataclass
class BreakerDiagnostics:
    """Collects transition history and computes availability percentages."""

    service_name: str
    _events: list[StateTransitionEvent] = field(default_factory=list)

    def record_transition(
        self, from_state: str, to_state: str, timestamp: float, reason: str
    ) -> None:
        """Append a state transition record if states differ."""
        if from_state == to_state:
            return
        self._events.append(
            StateTransitionEvent(
                service_name=self.service_name,
                from_state=from_state,
                to_state=to_state,
                timestamp=timestamp,
                reason=reason,
            )
        )

    @property
    def trip_count(self) -> int:
        """Count how many times the breaker entered the OPEN state."""
        return sum(1 for ev in self._events if ev.to_state == "open")

    def recent_events(self, limit: int = 5) -> list[StateTransitionEvent]:
        """Return the last `limit` state transitions."""
        return list(self._events[-limit:]) if limit > 0 else []

    def format_timeline(self) -> str:
        """Render recorded transitions as a concise arrow timeline."""
        if not self._events:
            return f"{self.service_name}: steady (no transitions)"
        steps = [
            f"{ev.from_state}->{ev.to_state}@{ev.timestamp:.1f}s({ev.reason})"
            for ev in self._events
        ]
        return f"{self.service_name}: " + " | ".join(steps)
