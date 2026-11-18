"""Pluggable Isolated Sandbox Backends (Process-Isolated & Hardened Docker Adapter)."""

from __future__ import annotations

import abc
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from swe_repair_agent.models import SandboxTestResult, StackFrame, TestFailureDetail
from swe_repair_agent.patcher import validate_sandbox_path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SANDBOX_RUNS_DIR = PROJECT_ROOT / ".sandbox_runs"

_SUMMARY_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|error|errors)")
_FAILURE_HEADER_RE = re.compile(r"^_{3,}\s+(.+?)\s+_{3,}$")
_SHORT_FRAME_RE = re.compile(r"^([^\s:][^:]*\.py):(\d+):\s+in\s+(\S+)")
_INLINE_LOC_RE = re.compile(r"^([^\s:][^:]*\.py):(\d+):\s+(\w*(?:Error|Exception|Warning)\b.*)$")


def parse_pytest_output(
    stdout: str,
    stderr: str,
    exit_code: int,
    duration_sec: float,
    timed_out: bool = False,
) -> SandboxTestResult:
    """Parse pytest `-q --tb=short` output into structured pass/fail counts and stacktraces."""
    combined = f"{stdout}\n{stderr}".strip()
    passed_count = 0
    failed_count = 0
    error_count = 0

    for count_str, kind in _SUMMARY_COUNT_RE.findall(combined):
        val = int(count_str)
        if kind == "passed":
            passed_count = val
        elif kind == "failed":
            failed_count = val
        elif kind in ("error", "errors"):
            error_count = val

    failures: list[TestFailureDetail] = []
    lines = stdout.splitlines()
    idx = 0
    while idx < len(lines):
        header_match = _FAILURE_HEADER_RE.match(lines[idx].strip())
        if header_match:
            test_name = header_match.group(1).strip()
            idx += 1
            block_lines: list[str] = []
            while idx < len(lines):
                cur = lines[idx]
                if _FAILURE_HEADER_RE.match(cur.strip()) or cur.startswith("==="):
                    break
                block_lines.append(cur)
                idx += 1

            frames: list[StackFrame] = []
            e_lines: list[str] = []
            exc_type = ""

            for b_idx, bline in enumerate(block_lines):
                fm = _SHORT_FRAME_RE.match(bline.strip())
                if fm:
                    code_ln = (
                        block_lines[b_idx + 1].strip()
                        if b_idx + 1 < len(block_lines)
                        and not block_lines[b_idx + 1].lstrip().startswith("E ")
                        else ""
                    )
                    frames.append(
                        StackFrame(
                            file_path=fm.group(1).replace("\\", "/"),
                            line=int(fm.group(2)),
                            func_name=fm.group(3),
                            code_line=code_ln,
                        )
                    )
                    continue

                im = _INLINE_LOC_RE.match(bline.strip())
                if im:
                    if not any(
                        f.file_path == im.group(1).replace("\\", "/")
                        and f.line == int(im.group(2))
                        for f in frames
                    ):
                        frames.append(
                            StackFrame(
                                file_path=im.group(1).replace("\\", "/"),
                                line=int(im.group(2)),
                                func_name="",
                                code_line="",
                            )
                        )
                    if not exc_type:
                        exc_type = im.group(3).split(":", 1)[0].strip()

                stripped = bline.lstrip()
                if stripped.startswith("E "):
                    err_body = stripped[2:].strip()
                    e_lines.append(err_body)
                    if not exc_type and ":" in err_body:
                        cand = err_body.split(":", 1)[0].strip()
                        if cand.isidentifier():
                            exc_type = cand

            failures.append(
                TestFailureDetail(
                    test_name=test_name,
                    exception_type=exc_type or "AssertionError",
                    message=" | ".join(e_lines[:3]),
                    traceback_excerpt="\n".join(block_lines).strip(),
                    frames=frames,
                )
            )
            continue
        idx += 1

    passed = (
        not timed_out
        and exit_code == 0
        and failed_count == 0
        and error_count == 0
    )

    return SandboxTestResult(
        passed=passed,
        exit_code=exit_code,
        passed_count=passed_count,
        failed_count=failed_count,
        error_count=error_count,
        duration_sec=round(duration_sec, 4),
        timed_out=timed_out,
        stdout=stdout,
        stderr=stderr,
        failures=failures,
    )


class SandboxBackend(abc.ABC):
    """Abstract base interface for isolated repository code execution sandboxes."""

    def __init__(
        self,
        sandbox_runs_root: Path | None = None,
        default_timeout_sec: float = 15.0,
    ) -> None:
        self.sandbox_runs_root = (sandbox_runs_root or DEFAULT_SANDBOX_RUNS_DIR).resolve()
        self.default_timeout_sec = default_timeout_sec

    def create_workspace(
        self, source_repo_dir: Path, run_id: str | None = None
    ) -> Path:
        """Copy `source_repo_dir` into an isolated ephemeral directory under `.sandbox_runs`."""
        src = source_repo_dir.resolve()
        if not src.exists() or not src.is_dir():
            raise FileNotFoundError(f"Source repository not found: {src}")

        self.sandbox_runs_root.mkdir(parents=True, exist_ok=True)
        rid = run_id or f"run_{uuid.uuid4().hex[:10]}"
        workspace = (self.sandbox_runs_root / rid).resolve()
        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)

        shutil.copytree(
            src,
            workspace,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", "*.pyo", ".pytest_cache", ".sandbox_runs"
            ),
        )
        return workspace

    def cleanup_workspace(self, workspace_dir: Path) -> None:
        """Delete the ephemeral sandbox workspace and prune empty `.sandbox_runs` root."""
        ws = workspace_dir.resolve()
        if ws.exists() and ws.is_relative_to(self.sandbox_runs_root):
            shutil.rmtree(ws, ignore_errors=True)
        if self.sandbox_runs_root.exists():
            try:
                remaining = list(self.sandbox_runs_root.iterdir())
                if not remaining:
                    self.sandbox_runs_root.rmdir()
            except OSError:
                pass

    @contextmanager
    def session(
        self, source_repo_dir: Path, run_id: str | None = None
    ) -> Iterator[Path]:
        """Context manager guaranteeing ephemeral workspace creation and cleanup."""
        workspace = self.create_workspace(source_repo_dir, run_id=run_id)
        try:
            yield workspace
        finally:
            self.cleanup_workspace(workspace)

    def read_file(self, workspace_dir: Path, rel_path: str) -> str:
        """Safely read a file inside the sandbox workspace."""
        target = validate_sandbox_path(workspace_dir, rel_path, protect_tests=False)
        return target.read_text(encoding="utf-8")

    @abc.abstractmethod
    def run_pytest(
        self, workspace_dir: Path, timeout_sec: float | None = None
    ) -> SandboxTestResult:
        """Execute pytest inside the isolated workspace and return structured diagnostics."""


class ProcessIsolatedSandbox(SandboxBackend):
    """Cross-platform subprocess-isolated sandbox enforcing strict pytest rootdir & plugin isolation."""

    def build_pytest_command(self, workspace_dir: Path) -> list[str]:
        ws = workspace_dir.resolve()
        return [
            sys.executable,
            "-m",
            "pytest",
            str(ws),
            f"--rootdir={ws}",
            "-o",
            "addopts=",
            "-q",
            "--tb=short",
        ]

    def run_pytest(
        self, workspace_dir: Path, timeout_sec: float | None = None
    ) -> SandboxTestResult:
        ws = workspace_dir.resolve()
        if not ws.is_relative_to(self.sandbox_runs_root):
            raise PermissionError(
                f"Workspace '{ws}' must reside inside sandbox root '{self.sandbox_runs_root}'."
            )

        timeout = timeout_sec if timeout_sec is not None else self.default_timeout_sec
        cmd = self.build_pytest_command(ws)
        env = {
            **os.environ,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONPATH": str(ws),
            "PYTHONDONTWRITEBYTECODE": "1",
        }

        t0 = time.perf_counter()
        try:
            completed = subprocess.run(
                cmd,
                cwd=str(ws),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            elapsed = time.perf_counter() - t0
            return parse_pytest_output(
                stdout=completed.stdout,
                stderr=completed.stderr,
                exit_code=completed.returncode,
                duration_sec=elapsed,
                timed_out=False,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.perf_counter() - t0
            out = exc.stdout if isinstance(exc.stdout, str) else ""
            err = exc.stderr if isinstance(exc.stderr, str) else ""
            return parse_pytest_output(
                stdout=out,
                stderr=f"{err}\nSandboxTimeoutError: pytest exceeded {timeout}s limit.",
                exit_code=124,
                duration_sec=elapsed,
                timed_out=True,
            )


class DockerContainerSandbox(SandboxBackend):
    """Container-isolated sandbox adapter building hardened network-disabled Docker commands."""

    def __init__(
        self,
        image: str = "python:3.11-slim",
        memory_limit: str = "512m",
        cpus: str = "1.0",
        pids_limit: int = 128,
        sandbox_runs_root: Path | None = None,
        default_timeout_sec: float = 20.0,
    ) -> None:
        super().__init__(
            sandbox_runs_root=sandbox_runs_root,
            default_timeout_sec=default_timeout_sec,
        )
        self.image = image
        self.memory_limit = memory_limit
        self.cpus = cpus
        self.pids_limit = pids_limit

    @staticmethod
    def is_available() -> bool:
        """Check whether the Docker CLI is installed on the host."""
        return shutil.which("docker") is not None

    def build_docker_command(self, workspace_dir: Path) -> list[str]:
        """Construct a hardened, air-gapped `docker run` command for repository test verification."""
        ws = workspace_dir.resolve()
        return [
            "docker",
            "run",
            "--rm",
            "--network=none",
            f"--memory={self.memory_limit}",
            f"--cpus={self.cpus}",
            f"--pids-limit={self.pids_limit}",
            "--security-opt=no-new-privileges",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "-e",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
            "-e",
            "PYTHONPATH=/workspace",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-v",
            f"{ws}:/workspace:rw",
            "-w",
            "/workspace",
            self.image,
            "python",
            "-m",
            "pytest",
            "/workspace",
            "--rootdir=/workspace",
            "-o",
            "addopts=",
            "-q",
            "--tb=short",
        ]

    def run_pytest(
        self, workspace_dir: Path, timeout_sec: float | None = None
    ) -> SandboxTestResult:
        if not self.is_available():
            raise RuntimeError(
                "Docker CLI is not installed on this host; use ProcessIsolatedSandbox instead."
            )
        ws = workspace_dir.resolve()
        timeout = timeout_sec if timeout_sec is not None else self.default_timeout_sec
        cmd = self.build_docker_command(ws)

        t0 = time.perf_counter()
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            elapsed = time.perf_counter() - t0
            return parse_pytest_output(
                stdout=completed.stdout,
                stderr=completed.stderr,
                exit_code=completed.returncode,
                duration_sec=elapsed,
                timed_out=False,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.perf_counter() - t0
            out = exc.stdout if isinstance(exc.stdout, str) else ""
            err = exc.stderr if isinstance(exc.stderr, str) else ""
            return parse_pytest_output(
                stdout=out,
                stderr=f"{err}\nDockerTimeoutError: container exceeded {timeout}s.",
                exit_code=124,
                duration_sec=elapsed,
                timed_out=True,
            )


def create_sandbox_backend(
    backend: str = "process",
    sandbox_runs_root: Path | None = None,
    timeout_sec: float = 15.0,
) -> SandboxBackend:
    """Factory creating either `ProcessIsolatedSandbox` or `DockerContainerSandbox`."""
    mode = backend.lower().strip()
    if mode == "docker":
        return DockerContainerSandbox(
            sandbox_runs_root=sandbox_runs_root, default_timeout_sec=timeout_sec
        )
    if mode == "auto" and DockerContainerSandbox.is_available():
        return DockerContainerSandbox(
            sandbox_runs_root=sandbox_runs_root, default_timeout_sec=timeout_sec
        )
    return ProcessIsolatedSandbox(
        sandbox_runs_root=sandbox_runs_root, default_timeout_sec=timeout_sec
    )
