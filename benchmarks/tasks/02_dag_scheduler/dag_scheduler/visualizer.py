"""ASCII and Graphviz DOT formatters for DAG inspection."""

from __future__ import annotations

from dag_scheduler.models import ExecutionPlan, TaskNode


def render_ascii_waves(plan: ExecutionPlan) -> str:
    """Format parallel execution waves into a readable multi-line ASCII diagram."""
    if not plan.parallel_waves:
        return "(empty plan)"
    lines: list[str] = []
    for idx, wave in enumerate(plan.parallel_waves):
        joined = ", ".join(wave)
        lines.append(f"Wave {idx}: [{joined}]")
    return "\n".join(lines)


def render_dot_graph(nodes: dict[str, TaskNode], graph_name: str = "workflow") -> str:
    """Export task dependencies as a Graphviz DOT directed graph string."""
    lines = [f"digraph {graph_name} {{", "  rankdir=LR;"]
    for tid in sorted(nodes):
        node = nodes[tid]
        lines.append(f'  "{tid}" [label="{tid} ({node.estimated_cost_ms}ms)"];')
        for dep in node.dependencies:
            lines.append(f'  "{dep}" -> "{tid}";')
    lines.append("}")
    return "\n".join(lines)
