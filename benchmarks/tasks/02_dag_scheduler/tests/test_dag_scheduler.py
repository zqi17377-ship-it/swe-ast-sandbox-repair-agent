"""Tests for DAGScheduler topological ordering, tie-breaking, and cycle detection."""

from __future__ import annotations

import pytest

from dag_scheduler import CycleDetectedError, DAGScheduler, MissingDependencyError


def test_diamond_dag_dependencies() -> None:
    sched = DAGScheduler()
    sched.add_task("extract")
    sched.add_task("transform_users", dependencies=["extract"])
    sched.add_task("transform_orders", dependencies=["extract"])
    sched.add_task("load_warehouse", dependencies=["transform_users", "transform_orders"])

    plan = sched.compile_plan()
    assert plan.ordered_ids == [
        "extract",
        "transform_orders",
        "transform_users",
        "load_warehouse",
    ]
    assert plan.parallel_waves == [
        ["extract"],
        ["transform_orders", "transform_users"],
        ["load_warehouse"],
    ]


def test_lexicographical_tie_breaking_independent_roots() -> None:
    sched = DAGScheduler()
    # Registered in reverse order; ready queue must tie-break lexicographically!
    sched.add_task("zeta")
    sched.add_task("beta")
    sched.add_task("alpha")
    sched.add_task("join", dependencies=["zeta", "alpha"])

    plan = sched.compile_plan()
    assert plan.ordered_ids == ["alpha", "beta", "zeta", "join"]


def test_three_node_cycle_raises_cycle_detected_error() -> None:
    sched = DAGScheduler()
    sched.add_task("init")
    sched.add_task("step_a", dependencies=["init", "step_c"])
    sched.add_task("step_b", dependencies=["step_a"])
    sched.add_task("step_c", dependencies=["step_b"])

    with pytest.raises(CycleDetectedError) as exc_info:
        sched.compile_plan()
    assert exc_info.value.cycle_nodes == ["step_a", "step_b", "step_c"]


def test_self_dependency_cycle_raises() -> None:
    sched = DAGScheduler()
    sched.add_task("mirror", dependencies=["mirror"])
    with pytest.raises(CycleDetectedError) as exc_info:
        sched.compile_plan()
    assert "mirror" in exc_info.value.cycle_nodes


def test_missing_dependency_raises() -> None:
    sched = DAGScheduler()
    sched.add_task("deploy", dependencies=["build_artifact"])
    with pytest.raises(MissingDependencyError):
        sched.compile_plan()
