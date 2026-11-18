"""Domain exceptions for DAG dependency resolution."""

from __future__ import annotations


class SchedulerError(Exception):
    """Base exception for DAG scheduling failures."""


class CycleDetectedError(SchedulerError):
    """Raised when a dependency graph contains one or more directed cycles."""

    def __init__(self, cycle_nodes: list[str]) -> None:
        self.cycle_nodes = sorted(cycle_nodes)
        joined = ", ".join(self.cycle_nodes)
        super().__init__(f"Cycle detected involving tasks: [{joined}]")


class MissingDependencyError(SchedulerError):
    """Raised when a task references an upstream dependency ID that is not registered."""

    def __init__(self, task_id: str, missing_dep: str) -> None:
        self.task_id = task_id
        self.missing_dep = missing_dep
        super().__init__(
            f"Task '{task_id}' depends on unregistered task '{missing_dep}'."
        )
