"""Tests for Container cycle detection, singleton sharing across child scopes, and scoped isolation."""

from __future__ import annotations

import itertools
import pytest

from dependency_injector import CircularDependencyError, Container, Scope


def test_detects_indirect_circular_dependency() -> None:
    c = Container()
    c.register("a", lambda b: b, scope=Scope.SINGLETON)
    c.register("b", lambda a: a, scope=Scope.SINGLETON)

    with pytest.raises(CircularDependencyError) as exc_info:
        c.resolve("a")
    assert exc_info.value.chain == ["a", "b", "a"]


def test_scoped_service_creates_fresh_instance_per_child_scope_even_after_parent_resolve() -> None:
    seq = itertools.count(1)
    root = Container()
    root.register("db_session", lambda: {"session_id": next(seq)}, scope=Scope.SCOPED)

    parent_sess = root.resolve("db_session")
    child_1 = root.create_child_scope()
    child_2 = root.create_child_scope()

    s1_a = child_1.resolve("db_session")
    s1_b = child_1.resolve("db_session")
    s2 = child_2.resolve("db_session")

    assert s1_a is s1_b
    assert s1_a["session_id"] != parent_sess["session_id"]
    assert s1_a["session_id"] != s2["session_id"]


def test_singleton_first_resolved_in_child_scope_is_shared_with_root_and_siblings() -> None:
    seq = itertools.count(100)
    root = Container()
    root.register("config_pool", lambda: {"pool_id": next(seq)}, scope=Scope.SINGLETON)

    child_1 = root.create_child_scope()
    child_2 = root.create_child_scope()

    first = child_1.resolve("config_pool")
    from_root = root.resolve("config_pool")
    from_sibling = child_2.resolve("config_pool")

    assert first is from_root
    assert first is from_sibling
