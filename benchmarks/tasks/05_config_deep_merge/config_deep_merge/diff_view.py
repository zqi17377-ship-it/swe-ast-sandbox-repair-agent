"""Structural diff computation between configuration snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConfigDiffEntry:
    """Single leaf difference between two nested dictionaries."""

    dotted_path: str
    old_value: Any
    new_value: Any
    change_kind: str


def compute_config_diff(
    before: dict[str, Any],
    after: dict[str, Any],
    prefix: str = "",
) -> list[ConfigDiffEntry]:
    """Recursively enumerate added, removed, and modified configuration keys."""
    diffs: list[ConfigDiffEntry] = []
    all_keys = sorted(set(before.keys()) | set(after.keys()))
    for key in all_keys:
        path = f"{prefix}.{key}" if prefix else str(key)
        if key not in before:
            diffs.append(ConfigDiffEntry(path, None, after[key], "added"))
        elif key not in after:
            diffs.append(ConfigDiffEntry(path, before[key], None, "removed"))
        else:
            v_old, v_new = before[key], after[key]
            if isinstance(v_old, dict) and isinstance(v_new, dict):
                diffs.extend(compute_config_diff(v_old, v_new, prefix=path))
            elif v_old != v_new:
                diffs.append(ConfigDiffEntry(path, v_old, v_new, "modified"))
    return diffs
