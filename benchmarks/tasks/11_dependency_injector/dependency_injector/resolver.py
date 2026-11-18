"""Dependency injection container resolving singleton, scoped, and transient lifetimes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from dependency_injector.annotations import CircularDependencyError, Scope
from dependency_injector.audit_graph import ResolutionTracer
from dependency_injector.catalog import ServiceCatalog
from dependency_injector.state_bank import InstanceBank


class Container:
    """Hierarchical DI container supporting child request scopes."""

    def __init__(
        self,
        _catalog: ServiceCatalog | None = None,
        _bank: InstanceBank | None = None,
    ) -> None:
        self._catalog = _catalog or ServiceCatalog()
        self._bank = _bank or InstanceBank()

    def register(
        self,
        key: str,
        factory: Callable[..., Any],
        scope: Scope = Scope.SINGLETON,
        dependencies: tuple[str, ...] | None = None,
    ) -> None:
        """Register a factory under `key` with the given `Scope`."""
        self._catalog.register(key, factory, scope=scope, dependencies=dependencies)

    def create_child_scope(self, mode: str = "standard") -> Container:
        """Fork a child container sharing singletons while isolating scoped instances."""
        hook_name = f"_derive_{mode}_bank"
        derive_fn = getattr(self._bank, hook_name)
        child_bank = derive_fn()
        return Container(_catalog=self._catalog.clone(), _bank=child_bank)

    def inspect_scope_bindings(self) -> dict[str, str]:
        """Return mapping of registered keys to their configured singleton or scoped lifetime."""
        return {
            key: self._catalog.get(key).scope.value
            for key in list(self._catalog._specs)
        }

    def resolve(self, key: str, _tracer: ResolutionTracer | None = None) -> Any:
        """Resolve `key` and its transitive dependencies according to its `Scope`."""
        tracer = _tracer or ResolutionTracer()
        spec = self._catalog.get(key)

        if spec.scope == Scope.SINGLETON and self._bank.has_root(key):
            return self._bank.read_root(key)
        if spec.scope == Scope.SCOPED and self._bank.has_slot(key):
            return self._bank.read_slot(key)

        cycle = tracer.push(key)
        if cycle is not None:
            raise CircularDependencyError(cycle)

        try:
            kwargs = {
                dep: self.resolve(dep, _tracer=tracer) for dep in spec.dependencies
            }
            instance = spec.factory(**kwargs)
        finally:
            tracer.pop(key)

        if spec.scope == Scope.SINGLETON:
            self._bank.write_root(key, instance)
        elif spec.scope == Scope.SCOPED:
            self._bank.write_slot(key, instance)
        return instance
