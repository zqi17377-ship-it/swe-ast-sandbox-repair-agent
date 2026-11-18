"""Safe Patch Engine with Path Traversal Protection and AST Pre-Commit Syntax Rollback."""

from __future__ import annotations

import ast
import difflib
import re
from pathlib import Path

from swe_repair_agent.models import PatchOutcome, SearchReplaceEdit


class SandboxSecurityError(PermissionError):
    """Raised when a file path attempts to escape the isolated sandbox root."""


class ProtectedPathError(PermissionError):
    """Raised when a patch attempts to modify protected test files."""


_SR_BLOCK_RE = re.compile(
    r"(?:<<<<<<<\s*FILE:\s*(?P<inline_file>[^\r\n]+)\r?\n|(?P<header_file>[A-Za-z0-9_./\\-]+\.py)\r?\n)?"
    r"<<<<<<<\s*SEARCH\r?\n"
    r"(?P<search>.*?)\r?\n"
    r"=======\r?\n"
    r"(?P<replace>.*?)\r?\n"
    r">>>>>>>\s*REPLACE",
    re.DOTALL,
)

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def validate_sandbox_path(
    sandbox_root: Path,
    rel_path: str,
    protect_tests: bool = True,
) -> Path:
    """Resolve `rel_path` strictly inside `sandbox_root`, blocking traversal and test edits."""
    cleaned = rel_path.strip().strip("`'\"").replace("\\", "/")
    if cleaned.startswith(("a/", "b/")) and not (sandbox_root / cleaned).exists():
        candidate_strip = cleaned[2:]
        if (sandbox_root / candidate_strip).exists() or "/" in candidate_strip:
            cleaned = candidate_strip

    raw_path = Path(cleaned)
    if raw_path.is_absolute() or re.match(r"^[A-Za-z]:", cleaned):
        raise SandboxSecurityError(
            f"Absolute path '{rel_path}' is forbidden inside sandbox."
        )

    root_resolved = sandbox_root.resolve()
    target_resolved = (root_resolved / cleaned).resolve()
    if not target_resolved.is_relative_to(root_resolved):
        raise SandboxSecurityError(
            f"Path traversal detected: '{rel_path}' escapes sandbox root."
        )

    norm_rel = target_resolved.relative_to(root_resolved).as_posix()
    if protect_tests and (
        norm_rel.startswith("tests/")
        or Path(norm_rel).name.startswith("test_")
        or "/tests/" in f"/{norm_rel}"
    ):
        raise ProtectedPathError(
            f"Modifying test file '{norm_rel}' is prohibited during code repair."
        )

    return target_resolved


def parse_search_replace_blocks(text: str) -> list[SearchReplaceEdit]:
    """Extract structured `SearchReplaceEdit` blocks from LLM output."""
    edits: list[SearchReplaceEdit] = []
    last_seen_file: str | None = None

    # Track standalone `FILE: path/to/file.py` markers as fallback
    file_marker_re = re.compile(r"^(?:FILE|Target File):\s*`?([A-Za-z0-9_./\\-]+\.py)`?\s*$", re.MULTILINE)
    markers = [(m.start(), m.group(1)) for m in file_marker_re.finditer(text)]

    for match in _SR_BLOCK_RE.finditer(text):
        file_path = match.group("inline_file") or match.group("header_file")
        if not file_path:
            pos = match.start()
            prior = [f for p, f in markers if p < pos]
            file_path = prior[-1] if prior else last_seen_file
        if not file_path:
            continue
        cleaned_fp = file_path.strip().strip("`'\"").replace("\\", "/")
        last_seen_file = cleaned_fp
        edits.append(
            SearchReplaceEdit(
                file_path=cleaned_fp,
                search=match.group("search"),
                replace=match.group("replace"),
            )
        )
    return edits


def _replace_snippet(content: str, search: str, replace: str) -> str | None:
    """Replace `search` with `replace` using exact match or trailing-whitespace-tolerant line match."""
    if search in content:
        return content.replace(search, replace, 1)

    content_lines = content.splitlines()
    search_lines = [ln.rstrip() for ln in search.splitlines()]
    if not search_lines:
        return None

    n_search = len(search_lines)
    for idx in range(len(content_lines) - n_search + 1):
        window = [ln.rstrip() for ln in content_lines[idx : idx + n_search]]
        if window == search_lines:
            new_lines = (
                content_lines[:idx]
                + replace.splitlines()
                + content_lines[idx + n_search :]
            )
            trailing_nl = "\n" if content.endswith("\n") else ""
            return "\n".join(new_lines) + trailing_nl
    return None


class SafePatchEngine:
    """Applies Search/Replace edits or unified diffs with transactional AST syntax rollback."""

    def __init__(self, protect_tests: bool = True) -> None:
        self.protect_tests = protect_tests

    def apply_edits(
        self,
        sandbox_root: Path,
        edits: list[SearchReplaceEdit],
    ) -> PatchOutcome:
        """Apply one or more Search/Replace edits atomically with `ast.parse()` verification."""
        if not edits:
            return PatchOutcome(
                applied=False,
                rolled_back=False,
                syntax_valid=True,
                error_type="EmptyPatchError",
                error_message="No SEARCH/REPLACE blocks were found in candidate response.",
            )

        backups: dict[Path, str] = {}
        staged: dict[Path, str] = {}
        rel_names: dict[Path, str] = {}

        try:
            for edit in edits:
                target_path = validate_sandbox_path(
                    sandbox_root, edit.file_path, protect_tests=self.protect_tests
                )
                if not target_path.exists():
                    return PatchOutcome(
                        applied=False,
                        rolled_back=False,
                        syntax_valid=True,
                        error_type="FileNotFoundError",
                        error_message=f"Target file '{edit.file_path}' does not exist in repository.",
                    )
                if target_path not in backups:
                    orig_text = target_path.read_text(encoding="utf-8")
                    backups[target_path] = orig_text
                    staged[target_path] = orig_text
                    rel_names[target_path] = (
                        target_path.resolve()
                        .relative_to(sandbox_root.resolve())
                        .as_posix()
                    )

                updated = _replace_snippet(staged[target_path], edit.search, edit.replace)
                if updated is None:
                    return PatchOutcome(
                        applied=False,
                        rolled_back=False,
                        syntax_valid=True,
                        error_type="SearchBlockMismatchError",
                        error_message=(
                            f"SEARCH block did not match existing source in '{rel_names[target_path]}'."
                        ),
                    )
                staged[target_path] = updated

        except (SandboxSecurityError, ProtectedPathError) as sec_err:
            raise sec_err

        return self._commit_with_ast_guard(sandbox_root, backups, staged, rel_names)

    def apply_unified_diff(
        self,
        sandbox_root: Path,
        diff_text: str,
    ) -> PatchOutcome:
        """Parse and apply a standard unified diff atomically with AST syntax rollback."""
        lines = diff_text.splitlines()
        idx = 0
        backups: dict[Path, str] = {}
        staged: dict[Path, str] = {}
        rel_names: dict[Path, str] = {}

        current_target: Path | None = None

        while idx < len(lines):
            line = lines[idx]
            if line.startswith("--- "):
                if idx + 1 < len(lines) and lines[idx + 1].startswith("+++ "):
                    plus_path = lines[idx + 1][4:].strip().split("\t")[0]
                    current_target = validate_sandbox_path(
                        sandbox_root, plus_path, protect_tests=self.protect_tests
                    )
                    if not current_target.exists():
                        return PatchOutcome(
                            applied=False,
                            error_type="FileNotFoundError",
                            error_message=f"Diff target '{plus_path}' does not exist.",
                        )
                    if current_target not in backups:
                        orig = current_target.read_text(encoding="utf-8")
                        backups[current_target] = orig
                        staged[current_target] = orig
                        rel_names[current_target] = (
                            current_target.resolve()
                            .relative_to(sandbox_root.resolve())
                            .as_posix()
                        )
                    idx += 2
                    continue

            if line.startswith("@@ ") and current_target is not None:
                m = _HUNK_HEADER_RE.match(line)
                if not m:
                    return PatchOutcome(
                        applied=False,
                        error_type="MalformedDiffError",
                        error_message=f"Invalid hunk header: {line}",
                    )
                orig_start = int(m.group(1))
                src_lines = staged[current_target].splitlines()
                idx += 1
                hunk_old: list[str] = []
                hunk_new: list[str] = []
                while idx < len(lines) and not lines[idx].startswith(("@@ ", "--- ", "diff --git")):
                    hl = lines[idx]
                    if hl.startswith("\\ No newline"):
                        idx += 1
                        continue
                    if hl.startswith(" "):
                        hunk_old.append(hl[1:])
                        hunk_new.append(hl[1:])
                    elif hl.startswith("-"):
                        hunk_old.append(hl[1:])
                    elif hl.startswith("+"):
                        hunk_new.append(hl[1:])
                    else:
                        hunk_old.append(hl)
                        hunk_new.append(hl)
                    idx += 1

                pos = max(0, orig_start - 1)
                if src_lines[pos : pos + len(hunk_old)] != hunk_old:
                    # Fallback sliding search for hunk_old
                    found_pos: int | None = None
                    for cand_pos in range(len(src_lines) - len(hunk_old) + 1):
                        if src_lines[cand_pos : cand_pos + len(hunk_old)] == hunk_old:
                            found_pos = cand_pos
                            break
                    if found_pos is None:
                        return PatchOutcome(
                            applied=False,
                            error_type="HunkMismatchError",
                            error_message=f"Unified diff hunk failed to match '{rel_names[current_target]}'.",
                        )
                    pos = found_pos

                updated_lines = src_lines[:pos] + hunk_new + src_lines[pos + len(hunk_old) :]
                trailing = "\n" if staged[current_target].endswith("\n") else ""
                staged[current_target] = "\n".join(updated_lines) + trailing
                continue

            idx += 1

        if not staged:
            return PatchOutcome(
                applied=False,
                error_type="EmptyDiffError",
                error_message="No valid file hunks found in unified diff.",
            )

        return self._commit_with_ast_guard(sandbox_root, backups, staged, rel_names)

    def _commit_with_ast_guard(
        self,
        sandbox_root: Path,
        backups: dict[Path, str],
        staged: dict[Path, str],
        rel_names: dict[Path, str],
    ) -> PatchOutcome:
        """Write staged edits, verify Python AST syntax, and roll back atomically on SyntaxError."""
        diff_chunks: list[str] = []
        modified_files: list[str] = []

        try:
            # Write candidate changes
            for path, new_text in staged.items():
                if new_text != backups[path]:
                    path.write_text(new_text, encoding="utf-8")
                    modified_files.append(rel_names[path])

            # Validate every touched Python file via ast.parse()
            for path, new_text in staged.items():
                if path.suffix == ".py":
                    ast.parse(new_text, filename=rel_names[path])

        except SyntaxError as syn_err:
            # Automatic atomic rollback of all touched files!
            for path, orig_text in backups.items():
                path.write_text(orig_text, encoding="utf-8")
            err_detail = (
                f"SyntaxError in '{syn_err.filename}' at line {syn_err.lineno}: {syn_err.msg}"
            )
            return PatchOutcome(
                applied=False,
                rolled_back=True,
                syntax_valid=False,
                modified_files=[],
                unified_diff="",
                error_type="SyntaxError",
                error_message=err_detail,
            )

        for path in sorted(staged, key=lambda p: rel_names[p]):
            orig_lines = backups[path].splitlines(keepends=True)
            new_lines = staged[path].splitlines(keepends=True)
            if orig_lines != new_lines:
                rel = rel_names[path]
                diff_chunks.append(
                    "".join(
                        difflib.unified_diff(
                            orig_lines,
                            new_lines,
                            fromfile=f"a/{rel}",
                            tofile=f"b/{rel}",
                        )
                    )
                )

        return PatchOutcome(
            applied=bool(modified_files),
            rolled_back=False,
            syntax_valid=True,
            modified_files=modified_files,
            unified_diff="\n".join(diff_chunks),
            error_type=None if modified_files else "NoOpPatchError",
            error_message=None if modified_files else "Patch produced no net file changes.",
        )


def compute_repo_diff(original_dir: Path, modified_dir: Path) -> str:
    """Generate a combined unified diff between `original_dir` and `modified_dir`."""
    orig_root = original_dir.resolve()
    mod_root = modified_dir.resolve()
    diffs: list[str] = []

    all_rel = sorted(
        {
            p.relative_to(orig_root).as_posix()
            for p in orig_root.rglob("*.py")
            if "__pycache__" not in p.parts
        }
        | {
            p.relative_to(mod_root).as_posix()
            for p in mod_root.rglob("*.py")
            if "__pycache__" not in p.parts
        }
    )

    for rel in all_rel:
        p_orig = orig_root / rel
        p_mod = mod_root / rel
        orig_lines = (
            p_orig.read_text(encoding="utf-8").splitlines(keepends=True)
            if p_orig.exists()
            else []
        )
        mod_lines = (
            p_mod.read_text(encoding="utf-8").splitlines(keepends=True)
            if p_mod.exists()
            else []
        )
        if orig_lines != mod_lines:
            diffs.append(
                "".join(
                    difflib.unified_diff(
                        orig_lines,
                        mod_lines,
                        fromfile=f"a/{rel}",
                        tofile=f"b/{rel}",
                    )
                )
            )
    return "\n".join(diffs)
