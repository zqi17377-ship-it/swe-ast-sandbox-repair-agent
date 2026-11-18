"""Task specification and compiled execution plan models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaskNode:
    """Single unit of work in a dependency graph."""

    task_id: str
    dependencies: tuple[str, ...] = ()
    estimated_cost_ms: int = 100
    owner: str = "core"
    retries: int = 0


@dataclass(frozen=True)
class ExecutionPlan:
    """Compiled topological order and parallelizable wave stages."""

    ordered_ids: list[str]
    parallel_waves: list[list[str]] = field(default_factory=list)
    total_tasks: int = 0

    @property
    def wave_count(self) -> int:
        return len(self.parallel_waves)
