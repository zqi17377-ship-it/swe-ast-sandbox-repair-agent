"""Immutable recursive deep-merge engine for multi-environment configuration layers."""

from __future__ import annotations

import copy
from typing import Any


def deep_merge_configs(
    base: dict[str, Any],
    override: dict[str, Any],
    list_strategy: str = "replace",
) -> dict[str, Any]:
    """Merge `override` on top of `base` without mutating or aliasing either input."""
    if list_strategy not in {"replace", "append_unique"}:
        raise ValueError(f"Unsupported list_strategy: {list_strategy}")

    # BUG: shallow `dict(base)` aliases nested dicts and lists from `base` and `override`!
    merged: dict[str, Any] = dict(base)
    for key, over_val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(over_val, dict):
            merged[key] = deep_merge_configs(
                merged[key], over_val, list_strategy=list_strategy
            )
        elif (
            list_strategy == "append_unique"
            and key in merged
            and isinstance(merged[key], list)
            and isinstance(over_val, list)
        ):
            combined = merged[key]
            for item in over_val:
                if item not in combined:
                    combined.append(item)
            merged[key] = combined
        else:
            merged[key] = over_val
    return merged


class EnvironmentProfileBuilder:
    """Builds isolated configuration dictionaries for dev, staging, and prod profiles."""

    def __init__(self, defaults: dict[str, Any]) -> None:
        self._defaults = copy.deepcopy(defaults)
        self._overlays: dict[str, dict[str, Any]] = {}

    def register_overlay(self, env_name: str, overlay: dict[str, Any]) -> None:
        """Register an environment-specific override mapping."""
        self._overlays[env_name] = copy.deepcopy(overlay)

    def build_profile(
        self, env_name: str, list_strategy: str = "replace"
    ) -> dict[str, Any]:
        """Compile effective profile for `env_name`."""
        overlay = self._overlays.get(env_name, {})
        return deep_merge_configs(
            self._defaults, overlay, list_strategy=list_strategy
        )
