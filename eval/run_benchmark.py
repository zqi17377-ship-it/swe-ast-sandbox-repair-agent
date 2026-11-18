"""3-Way SWE-bench-Style Ablation Benchmark Runner across 12 Multi-File Repositories."""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rich.console import Console
from rich.table import Table

from benchmarks.manifest import load_all_tasks, resolve_task_repo_path
from swe_repair_agent import AgentConfig, RepairRunResult, SWERepairAgent, create_repair_llm

ABLATION_CONFIGS: list[AgentConfig] = [
    AgentConfig(
        config_name="baseline_1_single_shot_full",
        label="Baseline 1: Single-Shot Full-Context (max_turns=1)",
        use_ast_localization=False,
        use_test_loop=False,
        max_turns=1,
        top_k_symbols=4,
        full_context_token_budget=1510,
    ),
    AgentConfig(
        config_name="baseline_2_multiturn_full",
        label="Baseline 2: Multi-Turn Full-Context (max_turns=4)",
        use_ast_localization=False,
        use_test_loop=True,
        max_turns=4,
        top_k_symbols=4,
        full_context_token_budget=1510,
    ),
    AgentConfig(
        config_name="ours_ast_self_healing",
        label="Ours: AST Localization + Sandbox Self-Healing (max_turns=4)",
        use_ast_localization=True,
        use_test_loop=True,
        max_turns=4,
        top_k_symbols=4,
        full_context_token_budget=1510,
    ),
]


def summarize_ablation(
    cfg: AgentConfig, runs: list[RepairRunResult]
) -> dict[str, Any]:
    """Compute aggregate SWE-bench-style repair, efficiency, and failure metrics."""
    n = len(runs)
    resolved_runs = [r for r in runs if r.resolved]
    first_turn_runs = [r for r in resolved_runs if r.resolved_on_turn == 1]
    healed_runs = [r for r in resolved_runs if (r.resolved_on_turn or 0) >= 2]

    avg_ctx_tokens = round(sum(r.avg_context_tokens for r in runs) / max(1, n), 1)
    avg_raw_tokens = round(sum(r.raw_repo_tokens for r in runs) / max(1, n), 1)
    avg_base_tokens = round(sum(r.full_baseline_tokens for r in runs) / max(1, n), 1)

    red_vs_raw_pct = round(
        (avg_raw_tokens - avg_ctx_tokens) / max(1.0, avg_raw_tokens) * 100.0, 2
    )
    red_vs_base_pct = round(
        (avg_base_tokens - avg_ctx_tokens) / max(1.0, avg_base_tokens) * 100.0, 2
    )

    avg_turns = round(sum(r.turns_used for r in runs) / max(1, n), 2)
    total_sb_sec = round(sum(r.total_sandbox_time_sec for r in runs), 3)
    avg_sb_sec = round(total_sb_sec / max(1, n), 3)
    syntax_rollbacks = sum(r.syntax_rollbacks for r in runs)

    failure_counts = Counter(
        r.failure_category for r in runs if not r.resolved
    )

    return {
        "config_name": cfg.config_name,
        "label": cfg.label,
        "use_ast_localization": cfg.use_ast_localization,
        "use_test_loop": cfg.use_test_loop,
        "max_turns": cfg.max_turns,
        "total_tasks": n,
        "resolved_count": len(resolved_runs),
        "resolved_pass_at_1_pct": round(len(resolved_runs) / max(1, n) * 100.0, 2),
        "first_turn_resolved_count": len(first_turn_runs),
        "first_turn_pass_pct": round(len(first_turn_runs) / max(1, n) * 100.0, 2),
        "self_healed_count": len(healed_runs),
        "self_healed_pct": round(len(healed_runs) / max(1, n) * 100.0, 2),
        "avg_context_tokens": avg_ctx_tokens,
        "avg_raw_repo_tokens": avg_raw_tokens,
        "avg_full_baseline_tokens": avg_base_tokens,
        "token_reduction_vs_baseline_pct": red_vs_base_pct,
        "token_reduction_vs_raw_pct": red_vs_raw_pct,
        "avg_repair_turns": avg_turns,
        "total_sandbox_time_sec": total_sb_sec,
        "avg_sandbox_time_sec": avg_sb_sec,
        "syntax_rollbacks_caught": syntax_rollbacks,
        "failure_category_counts": dict(sorted(failure_counts.items())),
    }


def generate_markdown_report(
    summaries: list[dict[str, Any]],
    runs_by_config: dict[str, list[RepairRunResult]],
) -> str:
    """Render `results/evaluation_report.md` from benchmark telemetry."""
    lines: list[str] = [
        "# SWE Code Repair Agent — 12-Repository Benchmark & 3-Way Ablation Report",
        "",
        "## 1. Executive Ablation Summary",
        "",
        "| Ablation Configuration | Resolved Pass@1 | First-Turn Pass | Self-Healed (T2–4) | Avg Context Tokens | Token Reduction (vs Raw / vs Base) | Avg Turns | Avg Sandbox Time |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for s in summaries:
        lines.append(
            f"| **{s['label']}** | **{s['resolved_count']}/{s['total_tasks']} ({s['resolved_pass_at_1_pct']:.1f}%)** | "
            f"{s['first_turn_resolved_count']}/{s['total_tasks']} ({s['first_turn_pass_pct']:.1f}%) | "
            f"{s['self_healed_count']}/{s['total_tasks']} ({s['self_healed_pct']:.1f}%) | "
            f"{s['avg_context_tokens']:.1f} | "
            f"{s['token_reduction_vs_raw_pct']:.1f}% / {s['token_reduction_vs_baseline_pct']:.1f}% | "
            f"{s['avg_repair_turns']:.2f} | {s['avg_sandbox_time_sec']:.2f}s |"
        )

    lines.extend(
        [
            "",
            "## 2. Per-Repository Outcome Matrix",
            "",
            "| Task ID | Category | B1: Single-Shot Full | B2: Multi-Turn Full | Ours: AST + Self-Healing | Ours Context Tokens (Raw) |",
            "| :--- | :--- | :---: | :---: | :---: | :---: |",
        ]
    )

    b1_map = {r.task_id: r for r in runs_by_config["baseline_1_single_shot_full"]}
    b2_map = {r.task_id: r for r in runs_by_config["baseline_2_multiturn_full"]}
    ours_map = {r.task_id: r for r in runs_by_config["ours_ast_self_healing"]}

    def _cell(r: RepairRunResult) -> str:
        if r.resolved:
            tag = " PASS (T1)" if r.resolved_on_turn == 1 else f" HEALED (T{r.resolved_on_turn})"
            return f"PASS:{tag}"
        return f"FAIL ({r.failure_category})"

    for task in load_all_tasks():
        tid = task.task_id
        r_ours = ours_map[tid]
        lines.append(
            f"| `{tid}` | {task.category} | {_cell(b1_map[tid])} | {_cell(b2_map[tid])} | "
            f"**{_cell(r_ours)}** | {r_ours.avg_context_tokens:.0f} ({r_ours.raw_repo_tokens}) |"
        )

    lines.extend(
        [
            "",
            "## 3. Failure Case Attribution Analysis (`Ours` & Baselines)",
            "",
            "### 3.1 Unresolved Tasks in `Ours: AST Localization + Sandbox Self-Healing`",
            "",
            "| Task ID | Turns Used | Final Pytest Status | Failure Category | Root-Cause Attribution |",
            "| :--- | :---: | :---: | :--- | :--- |",
        ]
    )

    for r in runs_by_config["ours_ast_self_healing"]:
        if not r.resolved:
            ft = r.final_test_result
            lines.append(
                f"| `{r.task_id}` | {r.turns_used} | {ft.passed_count}P / {ft.failed_count}F | "
                f"`{r.failure_category}` | {r.failure_explanation} |"
            )

    lines.extend(
        [
            "",
            "### 3.2 Aggregate Failure Distribution Across Ablations",
            "",
            "| Failure Category | B1: Single-Shot Full | B2: Multi-Turn Full | Ours: AST + Self-Healing |",
            "| :--- | :---: | :---: | :---: |",
        ]
    )

    all_cats = sorted(
        {
            cat
            for s in summaries
            for cat in s["failure_category_counts"]
        }
    )
    for cat in all_cats:
        c1 = summaries[0]["failure_category_counts"].get(cat, 0)
        c2 = summaries[1]["failure_category_counts"].get(cat, 0)
        c3 = summaries[2]["failure_category_counts"].get(cat, 0)
        lines.append(f"| `{cat}` | {c1} | {c2} | {c3} |")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    console = Console()
    tasks = load_all_tasks()
    llm = create_repair_llm(prefer_live=False)

    console.rule("[bold cyan]SWE Code Repair Benchmark — 12 Repos x 3 Ablations[/bold cyan]")
    t0 = time.perf_counter()

    summaries: list[dict[str, Any]] = []
    runs_by_config: dict[str, list[RepairRunResult]] = {}

    for cfg in ABLATION_CONFIGS:
        console.print(f"\n[bold yellow]Running:[/bold yellow] {cfg.label}")
        agent = SWERepairAgent(config=cfg, llm=llm)
        cfg_runs: list[RepairRunResult] = []

        for task in tasks:
            repo_dir = resolve_task_repo_path(task, PROJECT_ROOT)
            result = agent.repair_repository(task, repo_dir)
            cfg_runs.append(result)
            status_str = (
                f"[green]PASS (Turn {result.resolved_on_turn})[/green]"
                if result.resolved
                else f"[red]FAIL ({result.failure_category})[/red]"
            )
            console.print(
                f"  - {task.task_id:<28} {status_str} | "
                f"ctx={result.avg_context_tokens:.0f} tok | "
                f"turns={result.turns_used} | sb={result.total_sandbox_time_sec:.2f}s"
            )

        runs_by_config[cfg.config_name] = cfg_runs
        summaries.append(summarize_ablation(cfg, cfg_runs))

    elapsed = round(time.perf_counter() - t0, 2)

    table = Table(title="3-Way Ablation Benchmark Results (12 Multi-File Repositories)")
    table.add_column("Configuration", style="bold")
    table.add_column("Pass@1", justify="right")
    table.add_column("1st-Turn", justify="right")
    table.add_column("Self-Healed", justify="right")
    table.add_column("Avg Tokens", justify="right")
    table.add_column("Red. vs Raw", justify="right")
    table.add_column("Red. vs Base", justify="right")
    table.add_column("Avg Turns", justify="right")

    for s in summaries:
        table.add_row(
            s["label"],
            f"{s['resolved_count']}/{s['total_tasks']} ({s['resolved_pass_at_1_pct']:.1f}%)",
            f"{s['first_turn_pass_pct']:.1f}%",
            f"{s['self_healed_pct']:.1f}%",
            f"{s['avg_context_tokens']:.1f}",
            f"{s['token_reduction_vs_raw_pct']:.1f}%",
            f"{s['token_reduction_vs_baseline_pct']:.1f}%",
            f"{s['avg_repair_turns']:.2f}",
        )
    console.print()
    console.print(table)
    console.print(f"\nTotal benchmark wall-clock time: [bold]{elapsed:.2f}s[/bold]")

    results_dir = PROJECT_ROOT / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "benchmark_name": "Mini-SWE-Repair-12",
        "total_repositories": len(tasks),
        "total_wall_time_sec": elapsed,
        "ablation_summaries": summaries,
        "runs_by_config": {
            k: [r.model_dump(mode="json") for r in v]
            for k, v in runs_by_config.items()
        },
    }
    json_path = results_dir / "benchmark_results.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    md_report = generate_markdown_report(summaries, runs_by_config)
    md_path = results_dir / "evaluation_report.md"
    md_path.write_text(md_report, encoding="utf-8")

    console.print(f"Saved JSON telemetry -> {json_path}")
    console.print(f"Saved Markdown report -> {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
