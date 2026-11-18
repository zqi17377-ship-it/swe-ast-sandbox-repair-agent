"""Critical-path cost estimation and SLA telemetry for compiled DAG plans."""

from __future__ import annotations

from dataclasses import dataclass

from dag_scheduler.models import ExecutionPlan, TaskNode


@dataclass(frozen=True)
class CriticalPathReport:
    """Summary of critical path latency, total work, and parallelism speedup."""

    critical_path_ids: list[str]
    critical_path_ms: int
    sequential_total_ms: int
    parallelism_factor: float


def compute_critical_path(
    plan: ExecutionPlan, nodes: dict[str, TaskNode]
) -> CriticalPathReport:
    """Compute longest weighted dependency chain across a valid topological order."""
    if not plan.ordered_ids:
        return CriticalPathReport(
            critical_path_ids=[],
            critical_path_ms=0,
            sequential_total_ms=0,
            parallelism_factor=1.0,
        )

    best_cost: dict[str, int] = {}
    predecessor: dict[str, str | None] = {}

    for tid in plan.ordered_ids:
        node = nodes[tid]
        if not node.dependencies:
            best_cost[tid] = node.estimated_cost_ms
            predecessor[tid] = None
        else:
            best_dep = max(node.dependencies, key=lambda d: best_cost.get(d, 0))
            best_cost[tid] = best_cost[best_dep] + node.estimated_cost_ms
            predecessor[tid] = best_dep

    sink = max(plan.ordered_ids, key=lambda t: best_cost[t])
    chain: list[str] = []
    cur: str | None = sink
    while cur is not None:
        chain.append(cur)
        cur = predecessor[cur]
    chain.reverse()

    seq_ms = sum(nodes[t].estimated_cost_ms for t in plan.ordered_ids)
    cp_ms = best_cost[sink]
    speedup = round(seq_ms / cp_ms, 3) if cp_ms > 0 else 1.0

    return CriticalPathReport(
        critical_path_ids=chain,
        critical_path_ms=cp_ms,
        sequential_total_ms=seq_ms,
        parallelism_factor=speedup,
    )


def summarize_owner_load(nodes: dict[str, TaskNode]) -> dict[str, int]:
    """Aggregate total estimated execution milliseconds per team owner."""
    totals: dict[str, int] = {}
    for node in nodes.values():
        totals[node.owner] = totals.get(node.owner, 0) + node.estimated_cost_ms
    return dict(sorted(totals.items()))
