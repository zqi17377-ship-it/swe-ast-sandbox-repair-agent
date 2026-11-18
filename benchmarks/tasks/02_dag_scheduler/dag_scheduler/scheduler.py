"""Topological sort compiler and parallel wave planner for DAG workflows."""

from __future__ import annotations

import heapq
from collections import defaultdict, deque

from dag_scheduler.errors import CycleDetectedError, MissingDependencyError
from dag_scheduler.models import ExecutionPlan, TaskNode


class DAGScheduler:
    """Registers tasks with upstream dependencies and compiles deterministic execution plans."""

    def __init__(self) -> None:
        self._nodes: dict[str, TaskNode] = {}

    def add_task(
        self,
        task_id: str,
        dependencies: list[str] | tuple[str, ...] = (),
        estimated_cost_ms: int = 100,
        owner: str = "core",
    ) -> None:
        """Register or replace a task node in the workflow graph."""
        if not task_id or not task_id.strip():
            raise ValueError("task_id must be a non-empty string.")
        dedup_deps = tuple(dict.fromkeys(dependencies))
        self._nodes[task_id] = TaskNode(
            task_id=task_id,
            dependencies=dedup_deps,
            estimated_cost_ms=estimated_cost_ms,
            owner=owner,
        )

    def validate_dependencies(self) -> None:
        """Ensure all referenced upstream dependencies exist in the registry."""
        for task_id, node in self._nodes.items():
            for dep in node.dependencies:
                if dep not in self._nodes:
                    raise MissingDependencyError(task_id, dep)

    def compile_plan(self) -> ExecutionPlan:
        """Compile a lexicographically deterministic topological order and wave schedule."""
        if not self._nodes:
            return ExecutionPlan(ordered_ids=[], parallel_waves=[], total_tasks=0)

        self.validate_dependencies()

        in_degree: dict[str, int] = {tid: 0 for tid in self._nodes}
        dependents: dict[str, list[str]] = defaultdict(list)

        for tid, node in self._nodes.items():
            for dep in node.dependencies:
                in_degree[tid] += 1
                dependents[dep].append(tid)

        # BUG 1: uses insertion-order deque instead of min-heap lexicographical tie-breaking!
        # BUG 2: silently drops remaining cycle nodes instead of raising CycleDetectedError!
        ready = deque(tid for tid, deg in in_degree.items() if deg == 0)
        ordered: list[str] = []

        while ready:
            current = ready.popleft()
            ordered.append(current)
            for nxt in dependents[current]:
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    ready.append(nxt)

        waves = self._compute_waves(ordered)
        return ExecutionPlan(
            ordered_ids=ordered,
            parallel_waves=waves,
            total_tasks=len(ordered),
        )

    def _compute_waves(self, ordered_ids: list[str]) -> list[list[str]]:
        """Group scheduled tasks into concurrent execution waves by dependency depth."""
        depth: dict[str, int] = {}
        for tid in ordered_ids:
            deps = self._nodes[tid].dependencies
            depth[tid] = (
                0
                if not deps
                else 1 + max(depth[d] for d in deps if d in depth)
            )
        by_wave: dict[int, list[str]] = defaultdict(list)
        for tid in ordered_ids:
            by_wave[depth[tid]].append(tid)
        return [sorted(by_wave[w]) for w in sorted(by_wave)]
