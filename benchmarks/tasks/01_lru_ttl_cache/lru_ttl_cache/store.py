"""Core bounded LRU + TTL cache storage implementation."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from lru_ttl_cache.audit import AuditTrail
from lru_ttl_cache.config import CacheConfig, EvictionStrategy, validate_cache_config
from lru_ttl_cache.expiry import ClockFn, compute_deadline, is_expired, monotonic_clock
from lru_ttl_cache.metrics import CacheTelemetry


@dataclass
class _CacheEntry:
    value: Any
    created_at: float
    expires_at: float | None
    access_count: int = 0


class LRUTTLCache:
    """In-memory key-value store combining LRU capacity bounds with per-key TTL deadlines."""

    def __init__(
        self,
        config: CacheConfig | None = None,
        clock: ClockFn = monotonic_clock,
    ) -> None:
        self.config = validate_cache_config(config or CacheConfig())
        self._clock = clock
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self.telemetry = CacheTelemetry()
        self.audit = AuditTrail()

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: str, default: Any = None) -> Any:
        """Fetch key if present and unexpired; promote key in LRU order on hit."""
        now = self._clock()
        entry = self._entries.get(key)
        if entry is None:
            self.telemetry.record_miss(expired=False)
            return default

        if is_expired(entry.expires_at, now):
            # BUG: returns default on expired entry without deleting stale entry from _entries!
            self.telemetry.record_miss(expired=True)
            return default

        entry.access_count += 1
        if self.config.sliding_window and self.config.default_ttl is not None:
            entry.expires_at = compute_deadline(now, self.config.default_ttl)
        if self.config.strategy == EvictionStrategy.LRU:
            self._entries.move_to_end(key)
        self.telemetry.record_hit()
        return entry.value

    def put(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Insert or update `key` with optional per-entry TTL override."""
        now = self._clock()
        effective_ttl = ttl if ttl is not None else self.config.default_ttl
        deadline = compute_deadline(now, effective_ttl)

        if key in self._entries:
            existing = self._entries[key]
            existing.value = value
            existing.expires_at = deadline
            if self.config.strategy == EvictionStrategy.LRU:
                self._entries.move_to_end(key)
            self.telemetry.record_write()
            return

        # BUG: does not purge expired entries before evicting a live LRU entry at capacity!
        if len(self._entries) >= self.config.max_size:
            evicted_key, evicted_entry = self._entries.popitem(last=False)
            self.telemetry.record_capacity_eviction()
            if self.config.record_audit:
                self.audit.record(
                    evicted_key,
                    "capacity",
                    now,
                    evicted_entry.created_at,
                    evicted_entry.access_count,
                )

        self._entries[key] = _CacheEntry(
            value=value,
            created_at=now,
            expires_at=deadline,
            access_count=0,
        )
        self.telemetry.record_write()

    def purge_expired(self) -> int:
        """Remove all entries expired as of current clock timestamp."""
        now = self._clock()
        expired_keys = [
            k for k, entry in self._entries.items() if is_expired(entry.expires_at, now)
        ]
        for k in expired_keys:
            removed = self._entries.pop(k)
            if self.config.record_audit:
                self.audit.record(
                    k, "expired", now, removed.created_at, removed.access_count
                )
        return len(expired_keys)

    def delete(self, key: str) -> bool:
        """Explicitly delete a key if present."""
        if key in self._entries:
            del self._entries[key]
            return True
        return False

    def peek(self, key: str) -> Any:
        """Inspect value without updating LRU recency order."""
        now = self._clock()
        entry = self._entries.get(key)
        if entry is None or is_expired(entry.expires_at, now):
            return None
        return entry.value
