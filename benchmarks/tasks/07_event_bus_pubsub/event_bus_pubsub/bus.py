"""In-process publish/subscribe event bus supporting wildcards and one-shot listeners."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from event_bus_pubsub.envelope import DeliveryReport, EventEnvelope
from event_bus_pubsub.matcher import topic_matches

HandlerFn = Callable[[EventEnvelope], None]


@dataclass
class _Subscription:
    sub_id: int
    pattern: str
    handler: HandlerFn
    once: bool = False


class EventBus:
    """Dispatches hierarchical dot-delimited events to matching topic subscribers."""

    def __init__(self) -> None:
        self._next_id: int = 1
        self._subscriptions: list[_Subscription] = []

    def subscribe(self, pattern: str, handler: HandlerFn, once: bool = False) -> int:
        """Register `handler` for `pattern` and return an integer subscription ID."""
        if not pattern or not pattern.strip():
            raise ValueError("Subscription topic pattern cannot be empty.")
        sub_id = self._next_id
        self._next_id += 1
        self._subscriptions.append(
            _Subscription(sub_id=sub_id, pattern=pattern.strip(), handler=handler, once=once)
        )
        return sub_id

    def unsubscribe(self, sub_id: int) -> bool:
        """Remove a subscription by ID; return True if found."""
        for idx, sub in enumerate(self._subscriptions):
            if sub.sub_id == sub_id:
                del self._subscriptions[idx]
                return True
        return False

    def publish(
        self,
        topic: str,
        payload: dict[str, Any] | None = None,
        correlation_id: str = "",
    ) -> DeliveryReport:
        """Publish an event to `topic` and invoke all matching subscribers in order."""
        envelope = EventEnvelope(
            topic=topic.strip(),
            payload=dict(payload or {}),
            correlation_id=correlation_id,
        )
        invoked = 0
        # BUG: iterates directly over `self._subscriptions` while `once=True` or handler-triggered
        # `unsubscribe()` mutates `self._subscriptions`, skipping the immediately following subscriber!
        for sub in self._subscriptions:
            if topic_matches(sub.pattern, envelope.topic):
                if sub.once:
                    self.unsubscribe(sub.sub_id)
                sub.handler(envelope)
                invoked += 1

        return DeliveryReport(topic=envelope.topic, delivered_count=invoked)
