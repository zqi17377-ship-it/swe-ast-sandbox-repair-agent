"""Shared pytest fixtures ensuring all scratch workspaces stay inside project `.sandbox_runs`."""

from __future__ import annotations

import shutil
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

SANDBOX_RUNS_ROOT = PROJECT_ROOT / ".sandbox_runs"


@pytest.fixture()
def scratch_dir() -> Iterator[Path]:
    """Allocate an isolated test directory inside `03-f1-swe-code-repair/.sandbox_runs`."""
    base = SANDBOX_RUNS_ROOT / "_unit_scratch" / f"case_{uuid.uuid4().hex[:10]}"
    base.mkdir(parents=True, exist_ok=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)
        parent = SANDBOX_RUNS_ROOT / "_unit_scratch"
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
        if SANDBOX_RUNS_ROOT.exists() and not any(SANDBOX_RUNS_ROOT.iterdir()):
            SANDBOX_RUNS_ROOT.rmdir()
