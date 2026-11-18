"""Unit tests for AST symbol extraction, call-graph edges, fault localization, and token pruning."""

from __future__ import annotations

from pathlib import Path

from benchmarks.manifest import get_task_by_id, resolve_task_repo_path
from swe_repair_agent.ast_indexer import RepositoryASTIndexer
from swe_repair_agent.models import SandboxTestResult, StackFrame, TestFailureDetail


def test_ast_symbol_extraction_classes_methods_functions(scratch_dir: Path) -> None:
    pkg = scratch_dir / "calc"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "math_ops.py").write_text(
        '"""Math helpers."""\n\n'
        "def clamp(x: int, lo: int, hi: int) -> int:\n"
        '    """Clamp integer into [lo, hi]."""\n'
        "    return max(lo, min(hi, x))\n\n"
        "class Accumulator:\n"
        "    def __init__(self, start: int = 0) -> None:\n"
        "        self.total = start\n\n"
        "    def add_clamped(self, val: int) -> int:\n"
        "        self.total += clamp(val, 0, 100)\n"
        "        return self.total\n",
        encoding="utf-8",
    )

    indexer = RepositoryASTIndexer(scratch_dir)
    indexer.index()

    assert "calc/math_ops.py::clamp" in indexer.symbols
    assert "calc/math_ops.py::Accumulator" in indexer.symbols
    assert "calc/math_ops.py::Accumulator.add_clamped" in indexer.symbols
    method_sym = indexer.symbols["calc/math_ops.py::Accumulator.add_clamped"]
    assert method_sym.kind == "method"
    assert "clamp" in method_sym.calls


def test_cross_file_call_dependency_graph_edges(scratch_dir: Path) -> None:
    pkg = scratch_dir / "billing"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "tax.py").write_text(
        "def compute_vat(cents: int) -> int:\n"
        "    return (cents * 20) // 100\n",
        encoding="utf-8",
    )
    (pkg / "checkout.py").write_text(
        "from billing.tax import compute_vat\n\n"
        "def finalize_order(subtotal: int) -> int:\n"
        "    return subtotal + compute_vat(subtotal)\n",
        encoding="utf-8",
    )

    indexer = RepositoryASTIndexer(scratch_dir)
    indexer.index()

    edge_pairs = {(e.caller_id, e.callee_id) for e in indexer.edges}
    assert (
        "billing/checkout.py::finalize_order",
        "billing/tax.py::compute_vat",
    ) in edge_pairs


def test_hybrid_fault_localization_bm25_stacktrace_and_1hop_callee() -> None:
    task = get_task_by_id("01_lru_ttl_cache")
    repo_dir = resolve_task_repo_path(task)
    indexer = RepositoryASTIndexer(repo_dir)

    synthetic_fail = SandboxTestResult(
        passed=False,
        exit_code=1,
        passed_count=2,
        failed_count=1,
        failures=[
            TestFailureDetail(
                test_name="test_expired_get_removes_stale_entry_from_len",
                exception_type="AssertionError",
                message="Expired entry should be removed from storage upon get()",
                frames=[
                    StackFrame(
                        file_path="tests/test_lru_ttl_cache.py",
                        line=35,
                        func_name="test_expired_get_removes_stale_entry_from_len",
                    )
                ],
            )
        ],
    )

    ranked = indexer.localize_faults(
        task.issue_description, test_result=synthetic_fail, top_k=4
    )
    top_ids = {s.symbol_id for s in ranked}
    assert "lru_ttl_cache/store.py::LRUTTLCache.get" in top_ids
    assert "lru_ttl_cache/store.py::LRUTTLCache.put" in top_ids
    # 1-hop callee propagation pulls `expiry.py::is_expired` into top-4!
    assert "lru_ttl_cache/expiry.py::is_expired" in top_ids


def test_localized_context_achieves_over_40_percent_token_reduction() -> None:
    task = get_task_by_id("01_lru_ttl_cache")
    repo_dir = resolve_task_repo_path(task)
    indexer = RepositoryASTIndexer(repo_dir)

    bundle = indexer.build_localized_context(task.issue_description, top_k=4)
    assert bundle.context_tokens < bundle.raw_repo_tokens
    assert bundle.token_reduction_vs_raw_pct >= 45.0
    assert "# AST Repository Map" in bundle.prompt_context


def test_full_context_alphabetical_truncation_accounting() -> None:
    task = get_task_by_id("01_lru_ttl_cache")
    repo_dir = resolve_task_repo_path(task)
    indexer = RepositoryASTIndexer(repo_dir)

    full_bundle = indexer.build_full_context(token_budget=1550)
    assert full_bundle.context_tokens <= 1550
    assert "lru_ttl_cache/store.py" in full_bundle.truncated_files
