"""Unit tests for ProcessIsolatedSandbox & DockerContainerSandbox adapters."""

from __future__ import annotations

from pathlib import Path

from swe_repair_agent.sandbox import DockerContainerSandbox, ProcessIsolatedSandbox


def test_process_sandbox_isolated_workspace_lifecycle_and_cleanup(
    scratch_dir: Path,
) -> None:
    src_repo = scratch_dir / "mini_repo"
    (src_repo / "pkg").mkdir(parents=True)
    (src_repo / "tests").mkdir(parents=True)
    (src_repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (src_repo / "pkg" / "add.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8"
    )
    (src_repo / "tests" / "test_add.py").write_text(
        "from pkg.add import add\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    sandbox = ProcessIsolatedSandbox()
    captured_ws: Path | None = None
    with sandbox.session(src_repo) as ws:
        captured_ws = ws
        assert ws.exists()
        assert ws != src_repo.resolve()
        res = sandbox.run_pytest(ws)
        assert res.passed is True
        assert res.passed_count == 1
        # Mutate inside sandbox; source repo must remain untouched
        (ws / "pkg" / "add.py").write_text("# mutated\n", encoding="utf-8")

    assert captured_ws is not None and not captured_ws.exists()
    assert "return a + b" in (src_repo / "pkg" / "add.py").read_text(encoding="utf-8")


def test_process_sandbox_parses_pytest_failures_and_stack_frames(
    scratch_dir: Path,
) -> None:
    src_repo = scratch_dir / "buggy_repo"
    (src_repo / "mod").mkdir(parents=True)
    (src_repo / "tests").mkdir(parents=True)
    (src_repo / "mod" / "__init__.py").write_text("", encoding="utf-8")
    (src_repo / "mod" / "div.py").write_text(
        "def ratio(a: int, b: int) -> float:\n    return a / b\n", encoding="utf-8"
    )
    (src_repo / "tests" / "test_div.py").write_text(
        "from mod.div import ratio\ndef test_zero_div():\n    assert ratio(10, 0) == 0.0\n",
        encoding="utf-8",
    )

    sandbox = ProcessIsolatedSandbox()
    with sandbox.session(src_repo) as ws:
        res = sandbox.run_pytest(ws)
        assert res.passed is False
        assert res.failed_count == 1
        assert len(res.failures) == 1
        fail = res.failures[0]
        assert fail.test_name == "test_zero_div"
        assert "ZeroDivisionError" in fail.message
        assert any("mod/div.py" in fr.file_path for fr in fail.frames)


def test_process_sandbox_enforces_timeout_on_infinite_loop(scratch_dir: Path) -> None:
    src_repo = scratch_dir / "hang_repo"
    (src_repo / "tests").mkdir(parents=True)
    (src_repo / "tests" / "test_hang.py").write_text(
        "import time\ndef test_spin():\n    time.sleep(5.0)\n",
        encoding="utf-8",
    )

    sandbox = ProcessIsolatedSandbox(default_timeout_sec=1.2)
    with sandbox.session(src_repo) as ws:
        res = sandbox.run_pytest(ws, timeout_sec=1.2)
        assert res.passed is False
        assert res.timed_out is True
        assert res.exit_code == 124


def test_docker_container_sandbox_command_builder_hardening(scratch_dir: Path) -> None:
    docker_sb = DockerContainerSandbox(
        image="python:3.12-slim", memory_limit="256m", cpus="0.5", pids_limit=64
    )
    cmd = docker_sb.build_docker_command(scratch_dir)
    assert cmd[:4] == ["docker", "run", "--rm", "--network=none"]
    assert "--memory=256m" in cmd
    assert "--cpus=0.5" in cmd
    assert "--pids-limit=64" in cmd
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1" in cmd
    assert "--rootdir=/workspace" in cmd
