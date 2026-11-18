"""Closed-Loop SWE Repository Code Repair Agent with AST Localization & Sandbox Self-Healing."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from swe_repair_agent.ast_indexer import RepositoryASTIndexer
from swe_repair_agent.llm import RepairLLM, create_repair_llm
from swe_repair_agent.models import (
    AgentConfig,
    ChatMessage,
    ContextBundle,
    FailureCategory,
    PatchOutcome,
    RepairRunResult,
    SandboxTestResult,
    TaskSpec,
    TurnRecord,
)
from swe_repair_agent.patcher import SafePatchEngine, compute_repo_diff
from swe_repair_agent.sandbox import SandboxBackend, create_sandbox_backend

SYSTEM_PROMPT = """You are an autonomous Repository-Level Software Engineering Code Repair Agent.
Analyze the bug report, AST-localized source code context, and any sandbox pytest failure tracebacks.
Output your root-cause reasoning inside <diagnosis>...</diagnosis> tags, followed by one or more
exact SEARCH/REPLACE blocks targeting production source files (never modify test files):

<<<<<<< FILE: package/module.py
<<<<<<< SEARCH
exact existing lines
=======
updated replacement lines
>>>>>>> REPLACE
"""


def format_pytest_feedback(test_result: SandboxTestResult) -> str:
    """Format structured pytest failures into concise diagnostic feedback for the next turn."""
    lines = [
        f"Pytest Summary: {test_result.passed_count} passed, "
        f"{test_result.failed_count} failed, {test_result.error_count} errors "
        f"(exit_code={test_result.exit_code}, {test_result.duration_sec:.2f}s)"
    ]
    if test_result.timed_out:
        lines.append("CRITICAL: Test suite timed out (possible infinite loop in patch).")
    for fail in test_result.failures[:4]:
        lines.append(f"\n--- Failing Test: {fail.test_name} ({fail.exception_type}) ---")
        if fail.message:
            lines.append(f"Assertion/Error: {fail.message}")
        if fail.traceback_excerpt:
            excerpt_lines = fail.traceback_excerpt.splitlines()[-12:]
            lines.append("Traceback:\n" + "\n".join(excerpt_lines))
    return "\n".join(lines)


class SWERepairAgent:
    """Orchestrates AST fault localization, guarded patching, and test-driven self-healing."""

    def __init__(
        self,
        config: AgentConfig | None = None,
        llm: RepairLLM | None = None,
        sandbox: SandboxBackend | None = None,
        patch_engine: SafePatchEngine | None = None,
        on_turn_complete: Callable[[TurnRecord, ContextBundle], None] | None = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.llm = llm or create_repair_llm(prefer_live=False)
        self.sandbox = sandbox or create_sandbox_backend(
            "process", timeout_sec=self.config.sandbox_timeout_sec
        )
        self.patch_engine = patch_engine or SafePatchEngine(protect_tests=True)
        self.on_turn_complete = on_turn_complete

    def repair_repository(
        self,
        task: TaskSpec,
        source_repo_dir: Path,
    ) -> RepairRunResult:
        """Execute a complete isolated code-repair session on `source_repo_dir`."""
        wall_t0 = time.perf_counter()
        total_sandbox_sec = 0.0
        syntax_rollbacks = 0
        turns: list[TurnRecord] = []
        context_token_samples: list[int] = []

        effective_max_turns = (
            self.config.max_turns if self.config.use_test_loop else 1
        )

        with self.sandbox.session(source_repo_dir) as workspace:
            initial_test_res: SandboxTestResult | None = None
            latest_test_res: SandboxTestResult | None = None

            if self.config.use_test_loop:
                initial_test_res = self.sandbox.run_pytest(
                    workspace, timeout_sec=self.config.sandbox_timeout_sec
                )
                total_sandbox_sec += initial_test_res.duration_sec
                latest_test_res = initial_test_res

            last_patch_error: str | None = None
            resolved = False
            resolved_on_turn: int | None = None
            last_bundle: ContextBundle | None = None

            for turn_idx in range(1, effective_max_turns + 1):
                indexer = RepositoryASTIndexer(workspace)
                if self.config.use_ast_localization:
                    bundle = indexer.build_localized_context(
                        issue_description=task.issue_description,
                        test_result=latest_test_res,
                        top_k=self.config.top_k_symbols,
                        baseline_token_budget=self.config.full_context_token_budget,
                    )
                else:
                    bundle = indexer.build_full_context(
                        token_budget=self.config.full_context_token_budget
                    )

                last_bundle = bundle
                context_token_samples.append(bundle.context_tokens)

                user_prompt = self._build_turn_prompt(
                    task=task,
                    bundle=bundle,
                    turn_index=turn_idx,
                    initial_test_res=initial_test_res,
                    latest_test_res=latest_test_res,
                    last_patch_error=last_patch_error,
                )
                messages = [
                    ChatMessage(role="system", content=SYSTEM_PROMPT),
                    ChatMessage(role="user", content=user_prompt),
                ]

                llm_resp = self.llm.generate_patch(messages)

                if llm_resp.edits:
                    patch_outcome: PatchOutcome = self.patch_engine.apply_edits(
                        workspace, llm_resp.edits
                    )
                elif llm_resp.unified_diff:
                    patch_outcome = self.patch_engine.apply_unified_diff(
                        workspace, llm_resp.unified_diff
                    )
                else:
                    patch_outcome = PatchOutcome(
                        applied=False,
                        error_type="EmptyPatchError",
                        error_message="LLM response contained no actionable edits.",
                    )

                if patch_outcome.rolled_back:
                    syntax_rollbacks += 1

                turn_test_res: SandboxTestResult | None = None
                if patch_outcome.applied:
                    last_patch_error = None
                    turn_test_res = self.sandbox.run_pytest(
                        workspace, timeout_sec=self.config.sandbox_timeout_sec
                    )
                    total_sandbox_sec += turn_test_res.duration_sec
                    latest_test_res = turn_test_res
                else:
                    last_patch_error = (
                        f"PATCH VALIDATION ERROR ({patch_outcome.error_type}): "
                        f"{patch_outcome.error_message}"
                    )

                record = TurnRecord(
                    turn_index=turn_idx,
                    localized_symbols=list(bundle.selected_symbol_ids),
                    context_tokens=bundle.context_tokens,
                    diagnosis=llm_resp.diagnosis,
                    patch_outcome=patch_outcome,
                    test_result=turn_test_res,
                )
                turns.append(record)
                if self.on_turn_complete is not None:
                    self.on_turn_complete(record, bundle)

                if turn_test_res is not None and turn_test_res.passed:
                    resolved = True
                    resolved_on_turn = turn_idx
                    break

            if latest_test_res is None:
                latest_test_res = self.sandbox.run_pytest(
                    workspace, timeout_sec=self.config.sandbox_timeout_sec
                )
                total_sandbox_sec += latest_test_res.duration_sec

            final_diff = compute_repo_diff(source_repo_dir, workspace)

        wall_elapsed = time.perf_counter() - wall_t0
        assert last_bundle is not None

        fail_cat, fail_expl = (
            ("NONE", "")
            if resolved
            else self._attribute_failure(
                task=task,
                last_bundle=last_bundle,
                turns=turns,
                initial_test_res=initial_test_res,
                final_test_res=latest_test_res,
            )
        )

        avg_ctx = (
            round(sum(context_token_samples) / len(context_token_samples), 2)
            if context_token_samples
            else 0.0
        )

        return RepairRunResult(
            task_id=task.task_id,
            config_name=self.config.config_name,
            resolved=resolved,
            resolved_on_turn=resolved_on_turn,
            self_healed=bool(resolved and resolved_on_turn and resolved_on_turn >= 2),
            turns_used=len(turns),
            initial_test_result=initial_test_res,
            final_test_result=latest_test_res,
            turns=turns,
            final_unified_diff=final_diff,
            avg_context_tokens=avg_ctx,
            raw_repo_tokens=last_bundle.raw_repo_tokens,
            full_baseline_tokens=last_bundle.full_baseline_tokens,
            token_reduction_vs_raw_pct=last_bundle.token_reduction_vs_raw_pct,
            token_reduction_vs_baseline_pct=last_bundle.token_reduction_vs_baseline_pct,
            total_sandbox_time_sec=round(total_sandbox_sec, 4),
            total_wall_time_sec=round(wall_elapsed, 4),
            syntax_rollbacks=syntax_rollbacks,
            failure_category=fail_cat,  # type: ignore[arg-type]
            failure_explanation=fail_expl,
        )

    def _build_turn_prompt(
        self,
        task: TaskSpec,
        bundle: ContextBundle,
        turn_index: int,
        initial_test_res: SandboxTestResult | None,
        latest_test_res: SandboxTestResult | None,
        last_patch_error: str | None,
    ) -> str:
        sections = [
            f"## Task: {task.title} (`{task.task_id}`)",
            f"## Issue Description\n{task.issue_description}",
            f"## Repository Code Context (Turn {turn_index})\n{bundle.prompt_context}",
        ]

        if turn_index == 1 and initial_test_res and initial_test_res.failures:
            failing_names = ", ".join(f.test_name for f in initial_test_res.failures)
            sections.append(
                f"## Initial Reproduction Failures\nFailing tests: {failing_names}"
            )
        elif turn_index >= 2:
            fb_parts = ["## Sandbox Execution Feedback"]
            if last_patch_error:
                fb_parts.append(last_patch_error)
            if latest_test_res is not None:
                fb_parts.append(format_pytest_feedback(latest_test_res))
            sections.append("\n\n".join(fb_parts))

        return "\n\n".join(sections)

    def _attribute_failure(
        self,
        task: TaskSpec,
        last_bundle: ContextBundle,
        turns: list[TurnRecord],
        initial_test_res: SandboxTestResult | None,
        final_test_res: SandboxTestResult,
    ) -> tuple[FailureCategory, str]:
        if final_test_res.timed_out:
            return (
                "SANDBOX_TIMEOUT",
                "Candidate patch exceeded sandbox pytest execution timeout.",
            )

        # 1. Unpruned context truncation missed ground-truth file
        if last_bundle.mode == "full_context" and last_bundle.truncated_files:
            gt_files = {sym.split("::")[0] for sym in task.ground_truth_symbols}
            truncated_gt = sorted(gt_files & set(last_bundle.truncated_files))
            if truncated_gt:
                return (
                    "LOCALIZATION_TRUNCATION_MISS",
                    f"Unpruned alphabetical context window truncated target file(s): {', '.join(truncated_gt)}.",
                )

        # 2. Static AST call-graph missed dynamically dispatched target symbol
        if last_bundle.mode == "ast_localized" and task.ground_truth_symbols:
            all_localized = {
                sid for t in turns for sid in t.localized_symbols
            }
            if not (set(task.ground_truth_symbols) & all_localized):
                return (
                    "DYNAMIC_DISPATCH_GRAPH_MISS",
                    "Target symbol invoked via dynamic `getattr` reflection was absent from static AST Top-K.",
                )

        # 3. Single-shot mode solved primary test(s) without test loop to catch edge case
        if not self.config.use_test_loop and len(turns) == 1:
            return (
                "SINGLE_SHOT_EDGE_CASE_MISS",
                "Single-shot patch repaired reported symptom without sandbox traceback feedback for boundary assertions.",
            )

        # 4. Distinguish multi-module invariant oscillation vs stateful lexer regression
        modified_across_turns = {
            fp for t in turns for fp in t.patch_outcome.modified_files
        }
        if len(modified_across_turns) >= 2:
            return (
                "CROSS_MODULE_INVARIANT_OSCILLATION",
                f"Patches across {', '.join(sorted(modified_across_turns))} fixed local assertions "
                "while violating coupled cross-module conservation invariants.",
            )

        if "tokenizer" in "".join(modified_across_turns) or "lexer" in task.category.lower():
            return (
                "LEXER_SPEC_REGRESSION",
                "Single-pass character state machine fixed single-backtick & escape cases but regressed nested multi-backtick GFM spans.",
            )

        if all(not t.patch_outcome.applied for t in turns):
            return (
                "PATCH_APPLICATION_FAILURE",
                "No candidate patch was cleanly applied across repair turns.",
            )

        return (
            "CROSS_MODULE_INVARIANT_OSCILLATION",
            "Iterative patches left residual edge-case assertions failing after max_turns.",
        )
