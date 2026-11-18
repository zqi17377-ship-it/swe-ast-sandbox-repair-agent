"""Configuration models and validation rules for LRUTTLCache."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EvictionStrategy(str, Enum):
    """Supported cache capacity eviction policies."""

    LRU = "lru"
    FIFO = "fifo"


@dataclass(frozen=True)
class CacheConfig:
    """Validated runtime configuration for a bounded TTL cache."""

    max_size: int = 128
    default_ttl: float | None = 60.0
    strategy: EvictionStrategy = EvictionStrategy.LRU
    namespace: str = "default"
    record_audit: bool = True
    sliding_window: bool = False


def validate_cache_config(config: CacheConfig) -> CacheConfig:
    """Validate bounds on cache capacity, TTL duration, and namespace formatting."""
    if config.max_size <= 0:
        raise ValueError(f"max_size must be positive, got {config.max_size}")
    if config.default_ttl is not None and config.default_ttl <= 0.0:
        raise ValueError(
            f"default_ttl must be positive when set, got {config.default_ttl}"
        )
    cleaned_ns = config.namespace.strip()
    if not cleaned_ns or ":" in cleaned_ns:
        raise ValueError(
            f"namespace must be non-empty and cannot contain ':', got {config.namespace!r}"
        )
    return config


def qualify_cache_key(namespace: str, raw_key: str) -> str:
    """Build a canonical namespaced storage identifier."""
    if not raw_key:
        raise ValueError("Cache key must not be empty.")
    return f"{namespace}:{raw_key}"
