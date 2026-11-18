"""Provider lifetime scopes and dependency resolution error types."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any


class Scope(str, Enum):
    """Supported object lifetime policies."""

    SINGLETON = "singleton"
    SCOPED = "scoped"
    TRANSIENT = "transient"


class CircularDependencyError(RuntimeError):
    """Raised when provider resolution encounters a cycle in the active chain."""

    def __init__(self, chain: list[str]) -> None:
        self.chain = list(chain)
        rendered = " -> ".join(chain)
        super().__init__(f"Circular dependency detected: {rendered}")


@dataclass(frozen=True)
class ProviderSpec:
    """Registered factory and required dependency names for a service key."""

    key: str
    factory: Callable[..., Any]
    scope: Scope
    dependencies: tuple[str, ...] = ()
