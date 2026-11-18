"""End-to-end integration tests for SWERepairAgent closed-loop repair and ablation deltas."""

from __future__ import annotations

from benchmarks.manifest import get_task_by_id, resolve_task_repo_path
from swe_repair_agent import AgentConfig, MockRepairLLM, SWERepairAgent


def test_agent_e2e_single_turn_repair_on_dag_scheduler() -> None:
    task = get_task_by_id("02_dag_scheduler")
    repo_dir = resolve_task_repo_path(task)
    agent = SWERepairAgent(config=AgentConfig(), llm=MockRepairLLM())

    res = agent.repair_repository(task, repo_dir)
    assert res.resolved is True
    assert res.resolved_on_turn == 1
    assert res.self_healed is False
    assert res.final_test_result.passed_count == 5
    assert "CycleDetectedError" in res.final_unified_diff


def test_agent_e2e_multi_turn_self_healing_on_lru_ttl_cache() -> None:
    task = get_task_by_id("01_lru_ttl_cache")
    repo_dir = resolve_task_repo_path(task)
    agent = SWERepairAgent(config=AgentConfig(), llm=MockRepairLLM())

    res = agent.repair_repository(task, repo_dir)
    assert res.resolved is True
    assert res.resolved_on_turn == 2
    assert res.self_healed is True
    # Turn 1 repaired store.py (4P/1F), Turn 2 self-healed expiry.py (5P/0F)
    assert res.turns[0].test_result is not None
    assert res.turns[0].test_result.failed_count == 1
    assert res.final_test_result.passed is True
    assert res.token_reduction_vs_raw_pct >= 45.0


def test_agent_e2e_recovers_from_syntax_rollback_on_interval_merger() -> None:
    task = get_task_by_id("09_interval_merger")
    repo_dir = resolve_task_repo_path(task)
    agent = SWERepairAgent(config=AgentConfig(), llm=MockRepairLLM())

    res = agent.repair_repository(task, repo_dir)
    assert res.resolved is True
    assert res.resolved_on_turn == 3
    assert res.syntax_rollbacks == 1
    assert res.turns[1].patch_outcome.rolled_back is True
    assert res.turns[1].patch_outcome.error_type == "SyntaxError"


def test_agent_ablation_ast_localization_beats_truncated_full_context() -> None:
    task = get_task_by_id("06_pagination_cursor")
    repo_dir = resolve_task_repo_path(task)

    full_cfg = AgentConfig(
        config_name="full_base",
        use_ast_localization=False,
        use_test_loop=True,
        max_turns=2,
        full_context_token_budget=1550,
    )
    ours_cfg = AgentConfig(
        config_name="ours",
        use_ast_localization=True,
        use_test_loop=True,
        max_turns=2,
        top_k_symbols=4,
        full_context_token_budget=1550,
    )

    res_full = SWERepairAgent(config=full_cfg, llm=MockRepairLLM()).repair_repository(
        task, repo_dir
    )
    res_ours = SWERepairAgent(config=ours_cfg, llm=MockRepairLLM()).repair_repository(
        task, repo_dir
    )

    assert res_full.resolved is False
    assert res_full.failure_category == "LOCALIZATION_TRUNCATION_MISS"
    assert res_ours.resolved is True
    assert res_ours.avg_context_tokens < res_full.avg_context_tokens
