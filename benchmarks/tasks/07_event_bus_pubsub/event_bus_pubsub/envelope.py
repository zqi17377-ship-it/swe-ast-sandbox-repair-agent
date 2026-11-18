"""Immutable event payload envelopes and publish delivery receipts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EventEnvelope:
    """Published domain event with topic routing key and metadata."""

    topic: str
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""


@dataclass(frozen=True)
class DeliveryReport:
    """Summary returned after synchronous event dispatch."""

    topic: str
    delivered_count: int
