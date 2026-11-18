"""Lightweight Scoped Dependency Injection Container Package."""

from dependency_injector.annotations import CircularDependencyError, Scope
from dependency_injector.resolver import Container

__all__ = ["CircularDependencyError", "Container", "Scope"]
