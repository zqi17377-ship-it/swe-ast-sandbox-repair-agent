"""Tests for EventBus dispatch snapshot safety and hierarchical `*` vs `**` wildcard matching."""

from __future__ import annotations

from event_bus_pubsub import EventBus, EventEnvelope


def test_once_subscription_does_not_skip_subsequent_subscriber() -> None:
    bus = EventBus()
    seen: list[str] = []

    bus.subscribe("orders.created", lambda e: seen.append("once_listener"), once=True)
    bus.subscribe("orders.created", lambda e: seen.append("persistent_listener"))

    report1 = bus.publish("orders.created", {"id": 1})
    assert report1.delivered_count == 2
    assert seen == ["once_listener", "persistent_listener"]

    seen.clear()
    report2 = bus.publish("orders.created", {"id": 2})
    assert report2.delivered_count == 1
    assert seen == ["persistent_listener"]


def test_self_unsubscribe_inside_handler_delivers_to_all_peers() -> None:
    bus = EventBus()
    calls: list[str] = []
    sub_ref: list[int] = []

    def self_removing(_env: EventEnvelope) -> None:
        calls.append("first")
        bus.unsubscribe(sub_ref[0])

    sub_ref.append(bus.subscribe("auth.login", self_removing))
    bus.subscribe("auth.login", lambda _e: calls.append("second"))
    bus.subscribe("auth.login", lambda _e: calls.append("third"))

    bus.publish("auth.login")
    assert calls == ["first", "second", "third"]


def test_single_star_matches_single_segment_only_while_double_star_matches_multi() -> None:
    bus = EventBus()
    single_hits: list[str] = []
    multi_hits: list[str] = []

    bus.subscribe("orders.*", lambda e: single_hits.append(e.topic))
    bus.subscribe("orders.**", lambda e: multi_hits.append(e.topic))

    bus.publish("orders.created")
    bus.publish("orders.eu.paid")
    bus.publish("orders.us.west.refunded")

    assert single_hits == ["orders.created"]
    assert multi_hits == [
        "orders.created",
        "orders.eu.paid",
        "orders.us.west.refunded",
    ]
