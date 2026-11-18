"""Bounded dead-letter queue and event replay history store."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from event_bus_pubsub.envelope import EventEnvelope


@dataclass(frozen=True)
class DeadLetterRecord:
    """Captures a failed event dispatch for inspection or later replay."""

    envelope: EventEnvelope
    subscriber_pattern: str
    error_message: str


@dataclass
class EventReplayBuffer:
    """Ring buffer storing published envelopes and dead-letter failures."""

    max_history: int = 500
    _published: deque[EventEnvelope] = field(default_factory=deque)
    _dead_letters: list[DeadLetterRecord] = field(default_factory=list)

    def record_published(self, envelope: EventEnvelope) -> None:
        """Append a published envelope to bounded replay history."""
        self._published.append(envelope)
        while len(self._published) > self.max_history:
            self._published.popleft()

    def record_dead_letter(
        self,
        envelope: EventEnvelope,
        subscriber_pattern: str,
        error_message: str,
    ) -> None:
        """Record a handler failure in the dead-letter log."""
        self._dead_letters.append(
            DeadLetterRecord(
                envelope=envelope,
                subscriber_pattern=subscriber_pattern,
                error_message=error_message,
            )
        )

    def filter_by_prefix(self, prefix: str) -> list[EventEnvelope]:
        """Return buffered envelopes whose topic starts with `prefix`."""
        return [env for env in self._published if env.topic.startswith(prefix)]

    def dead_letter_summary(self) -> dict[str, int]:
        """Count dead-letter occurrences grouped by subscriber pattern."""
        counts: dict[str, int] = {}
        for rec in self._dead_letters:
            counts[rec.subscriber_pattern] = counts.get(rec.subscriber_pattern, 0) + 1
        return counts
