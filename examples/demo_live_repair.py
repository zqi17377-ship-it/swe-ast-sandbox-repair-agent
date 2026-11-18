"""Live Rich CLI Walkthrough: Multi-Turn Self-Healing Code Repair on `01_lru_ttl_cache`."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from benchmarks.manifest import get_task_by_id, resolve_task_repo_path
from swe_repair_agent import (
    AgentConfig,
    ContextBundle,
    SWERepairAgent,
    create_repair_llm,
)
from swe_repair_agent.models import TurnRecord


def main() -> int:
    console = Console()
    task = get_task_by_id("01_lru_ttl_cache")
    repo_dir = resolve_task_repo_path(task, PROJECT_ROOT)

    console.rule("[bold bright_cyan]SWE Code Repair Agent — Live Self-Healing Walkthrough[/bold bright_cyan]")
    console.print(
        Panel(
            f"[bold]Task ID:[/bold] {task.task_id}\n"
            f"[bold]Title:[/bold] {task.title}\n\n"
            f"[bold yellow]Bug Report:[/bold yellow]\n{task.issue_description}",
            title="Target Multi-File Repository Issue",
            border_style="cyan",
        )
    )

    def on_turn(turn: TurnRecord, bundle: ContextBundle) -> None:
        console.rule(f"[bold magenta]Repair Turn {turn.turn_index}[/bold magenta]")

        loc_table = Table(
            title=(
                f"AST Hybrid Fault Localization (Turn {turn.turn_index}) — "
                f"Prompt Context: {bundle.context_tokens} tokens "
                f"({bundle.token_reduction_vs_raw_pct:.1f}% reduction vs {bundle.raw_repo_tokens} raw repo tokens)"
            )
        )
        loc_table.add_column("Rank", justify="right", style="cyan")
        loc_table.add_column("Symbol ID", style="bold")
        loc_table.add_column("BM25", justify="right")
        loc_table.add_column("Trace/Test", justify="right")
        loc_table.add_column("1-Hop Graph", justify="right")
        loc_table.add_column("Total", justify="right", style="green")
        loc_table.add_column("Signals")

        for rank, sym in enumerate(bundle.ranked_symbols, start=1):
            loc_table.add_row(
                str(rank),
                sym.symbol_id,
                f"{sym.bm25_score:.2f}",
                f"{sym.stacktrace_score:.2f}",
                f"{sym.graph_score:.2f}",
                f"{sym.total_score:.2f}",
                ", ".join(sym.reasons[:3]),
            )
        console.print(loc_table)

        console.print(
            Panel(
                turn.diagnosis,
                title=f"Turn {turn.turn_index} Root-Cause Diagnosis",
                border_style="yellow",
            )
        )

        if turn.patch_outcome.unified_diff:
            console.print(
                Panel(
                    Syntax(turn.patch_outcome.unified_diff, "diff", theme="monokai"),
                    title=(
                        f"Turn {turn.turn_index} Candidate Patch "
                        f"(ast.parse Valid={turn.patch_outcome.syntax_valid})"
                    ),
                    border_style="blue",
                )
            )

        if turn.test_result is not None:
            tr = turn.test_result
            if tr.passed:
                console.print(
                    Panel(
                        f"[bold green]ALL TESTS PASSED![/bold green] "
                        f"({tr.passed_count} passed, {tr.failed_count} failed in {tr.duration_sec:.2f}s)",
                        title=f"Sandbox Pytest Verification (Turn {turn.turn_index})",
                        border_style="green",
                    )
                )
            else:
                fail_lines = [
                    f"[bold red]{tr.passed_count} passed, {tr.failed_count} failed[/bold red] "
                    f"({tr.duration_sec:.2f}s)"
                ]
                for f in tr.failures:
                    fail_lines.append(f"\n• {f.test_name}: {f.message}")
                console.print(
                    Panel(
                        "\n".join(fail_lines),
                        title=f"Sandbox Pytest Feedback -> Self-Healing Trigger (Turn {turn.turn_index})",
                        border_style="red",
                    )
                )

    config = AgentConfig(
        config_name="demo_ours",
        use_ast_localization=True,
        use_test_loop=True,
        max_turns=4,
        top_k_symbols=4,
    )
    agent = SWERepairAgent(
        config=config,
        llm=create_repair_llm(prefer_live=False),
        on_turn_complete=on_turn,
    )
    result = agent.repair_repository(task, repo_dir)

    console.rule("[bold green]Final Cumulative Repository Diff[/bold green]")
    console.print(Syntax(result.final_unified_diff, "diff", theme="monokai"))
    console.print(
        f"\n[bold green]Summary:[/bold green] Resolved={result.resolved} on Turn {result.resolved_on_turn} "
        f"(Self-Healed={result.self_healed}) | Avg Context={result.avg_context_tokens:.0f} tokens "
        f"({result.token_reduction_vs_raw_pct:.1f}% reduction) | Total Sandbox={result.total_sandbox_time_sec:.2f}s"
    )
    return 0 if result.resolved else 1


if __name__ == "__main__":
    raise SystemExit(main())
