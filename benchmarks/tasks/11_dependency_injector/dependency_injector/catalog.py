"""Service registration catalog with signature introspection."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from dependency_injector.annotations import ProviderSpec, Scope


class ServiceCatalog:
    """Immutable-on-fork registry of `ProviderSpec` definitions."""

    def __init__(self, initial: dict[str, ProviderSpec] | None = None) -> None:
        self._specs: dict[str, ProviderSpec] = dict(initial or {})

    def register(
        self,
        key: str,
        factory: Callable[..., Any],
        scope: Scope = Scope.SINGLETON,
        dependencies: tuple[str, ...] | None = None,
    ) -> None:
        """Register a service provider, inferring parameter dependencies if omitted."""
        if dependencies is None:
            sig = inspect.signature(factory)
            inferred = [
                name
                for name, param in sig.parameters.items()
                if param.default is inspect.Parameter.empty
                and param.kind
                in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
            ]
            deps = tuple(inferred)
        else:
            deps = tuple(dependencies)
        self._specs[key] = ProviderSpec(
            key=key, factory=factory, scope=scope, dependencies=deps
        )

    def get(self, key: str) -> ProviderSpec:
        if key not in self._specs:
            raise KeyError(f"Unregistered service provider: '{key}'")
        return self._specs[key]

    def clone(self) -> ServiceCatalog:
        return ServiceCatalog(self._specs)
