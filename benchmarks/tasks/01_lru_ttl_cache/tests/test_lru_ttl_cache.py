"""Test suite for LRUTTLCache covering lazy expiration, capacity purge, and boundary semantics."""

from __future__ import annotations

from lru_ttl_cache import CacheConfig, LRUTTLCache


class FakeClock:
    def __init__(self, initial: float = 1000.0) -> None:
        self.now = initial

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_basic_lru_eviction_order() -> None:
    clock = FakeClock()
    cache = LRUTTLCache(CacheConfig(max_size=2, default_ttl=60.0), clock=clock)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1  # 'a' becomes MRU, 'b' is LRU
    cache.put("c", 3)
    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3


def test_expired_get_removes_stale_entry_from_len() -> None:
    clock = FakeClock()
    cache = LRUTTLCache(CacheConfig(max_size=3, default_ttl=10.0), clock=clock)
    cache.put("k1", "v1")
    clock.advance(12.0)
    assert cache.get("k1") is None
    assert len(cache) == 0, "Expired entry should be removed from storage upon get()"


def test_put_at_capacity_purges_expired_before_evicting_live_lru() -> None:
    clock = FakeClock()
    cache = LRUTTLCache(CacheConfig(max_size=2, default_ttl=30.0), clock=clock)
    cache.put("live_old", "keep_me", ttl=30.0)
    cache.put("short_lived", "expire_me", ttl=5.0)

    clock.advance(6.0)
    # 'short_lived' is now expired; inserting 'new_key' must NOT evict 'live_old'!
    cache.put("new_key", "fresh", ttl=30.0)

    assert cache.get("live_old") == "keep_me"
    assert cache.get("new_key") == "fresh"
    assert cache.telemetry.capacity_evictions == 0


def test_exact_ttl_boundary_is_treated_as_expired() -> None:
    clock = FakeClock(500.0)
    cache = LRUTTLCache(CacheConfig(max_size=4, default_ttl=10.0), clock=clock)
    cache.put("session:1", {"user": "alice"}, ttl=10.0)
    clock.advance(9.999)
    assert cache.get("session:1") == {"user": "alice"}

    clock.advance(0.001)  # Exact deadline: now == 510.0 == created_at + ttl
    assert cache.get("session:1") is None
    assert len(cache) == 0


def test_overwrite_existing_key_resets_created_and_ttl() -> None:
    clock = FakeClock(100.0)
    cache = LRUTTLCache(CacheConfig(max_size=2, default_ttl=10.0), clock=clock)
    cache.put("token", "old", ttl=5.0)
    clock.advance(6.0)
    cache.put("token", "renewed", ttl=10.0)
    clock.advance(8.0)
    assert cache.get("token") == "renewed"
