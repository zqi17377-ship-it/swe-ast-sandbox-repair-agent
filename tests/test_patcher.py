"""Unit tests for SafePatchEngine: Search/Replace, Unified Diff, AST Rollback, and Path Guards."""

from __future__ import annotations

from pathlib import Path

import pytest

from swe_repair_agent.patcher import (
    ProtectedPathError,
    SafePatchEngine,
    SandboxSecurityError,
    parse_search_replace_blocks,
)


def test_parse_and_apply_search_replace_blocks(scratch_dir: Path) -> None:
    pkg = scratch_dir / "app"
    pkg.mkdir()
    target = pkg / "logic.py"
    target.write_text(
        "def discount(price: float) -> float:\n"
        "    return price * 1.10\n",
        encoding="utf-8",
    )

    llm_output = (
        "<diagnosis>Fix multiplier from 1.10 to 0.90.</diagnosis>\n"
        "<<<<<<< FILE: app/logic.py\n"
        "<<<<<<< SEARCH\n"
        "    return price * 1.10\n"
        "=======\n"
        "    return round(price * 0.90, 2)\n"
        ">>>>>>> REPLACE\n"
    )
    edits = parse_search_replace_blocks(llm_output)
    assert len(edits) == 1

    engine = SafePatchEngine()
    outcome = engine.apply_edits(scratch_dir, edits)
    assert outcome.applied is True
    assert outcome.syntax_valid is True
    assert outcome.rolled_back is False
    assert "round(price * 0.90, 2)" in target.read_text(encoding="utf-8")
    assert "-    return price * 1.10" in outcome.unified_diff


def test_ast_precommit_syntax_error_triggers_atomic_rollback(scratch_dir: Path) -> None:
    pkg = scratch_dir / "app"
    pkg.mkdir()
    original_code = "def compute(a: int, b: int) -> int:\n    return a + b\n"
    target = pkg / "core.py"
    target.write_text(original_code, encoding="utf-8")

    bad_patch = (
        "<<<<<<< FILE: app/core.py\n"
        "<<<<<<< SEARCH\n"
        "    return a + b\n"
        "=======\n"
        "    return (a + b\n"
        ">>>>>>> REPLACE\n"
    )
    engine = SafePatchEngine()
    outcome = engine.apply_edits(scratch_dir, parse_search_replace_blocks(bad_patch))

    assert outcome.applied is False
    assert outcome.syntax_valid is False
    assert outcome.rolled_back is True
    assert outcome.error_type == "SyntaxError"
    # File on disk MUST remain byte-for-byte identical to original_code!
    assert target.read_text(encoding="utf-8") == original_code


def test_path_traversal_and_absolute_paths_blocked(scratch_dir: Path) -> None:
    engine = SafePatchEngine()
    traversal_patch = parse_search_replace_blocks(
        "<<<<<<< FILE: ../../outside.py\n"
        "<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE"
    )
    with pytest.raises(SandboxSecurityError):
        engine.apply_edits(scratch_dir, traversal_patch)

    abs_patch = parse_search_replace_blocks(
        "<<<<<<< FILE: C:/Windows/System32/evil.py\n"
        "<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE"
    )
    with pytest.raises(SandboxSecurityError):
        engine.apply_edits(scratch_dir, abs_patch)


def test_protected_test_suite_files_cannot_be_modified(scratch_dir: Path) -> None:
    tests_dir = scratch_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_core.py").write_text("def test_ok():\n    assert False\n", encoding="utf-8")

    cheat_patch = parse_search_replace_blocks(
        "<<<<<<< FILE: tests/test_core.py\n"
        "<<<<<<< SEARCH\n    assert False\n=======\n    assert True\n>>>>>>> REPLACE"
    )
    engine = SafePatchEngine(protect_tests=True)
    with pytest.raises(ProtectedPathError):
        engine.apply_edits(scratch_dir, cheat_patch)


def test_apply_unified_diff_and_rollback_on_invalid_syntax(scratch_dir: Path) -> None:
    pkg = scratch_dir / "svc"
    pkg.mkdir()
    target = pkg / "handler.py"
    orig = "def greet(name: str) -> str:\n    return f'hi {name}'\n"
    target.write_text(orig, encoding="utf-8")

    valid_diff = (
        "--- a/svc/handler.py\n"
        "+++ b/svc/handler.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def greet(name: str) -> str:\n"
        "-    return f'hi {name}'\n"
        "+    return f'hello, {name}!'\n"
    )
    engine = SafePatchEngine()
    ok_res = engine.apply_unified_diff(scratch_dir, valid_diff)
    assert ok_res.applied is True
    assert "hello, {name}!" in target.read_text(encoding="utf-8")

    broken_diff = (
        "--- a/svc/handler.py\n"
        "+++ b/svc/handler.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def greet(name: str) -> str:\n"
        "-    return f'hello, {name}!'\n"
        "+    return f'hello, {name}!\n"
    )
    bad_res = engine.apply_unified_diff(scratch_dir, broken_diff)
    assert bad_res.applied is False
    assert bad_res.rolled_back is True
    assert "hello, {name}!" in target.read_text(encoding="utf-8")
