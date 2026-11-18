"""Schema path assertions and effective configuration reporting."""

from __future__ import annotations

from typing import Any


def lookup_dotted_path(config: dict[str, Any], dotted_path: str) -> Any:
    """Retrieve a value at a dot-delimited path or raise `KeyError`."""
    cur: Any = config
    for part in dotted_path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(f"Missing configuration path: '{dotted_path}'")
        cur = cur[part]
    return cur


def validate_required_paths(
    config: dict[str, Any], required_paths: list[str]
) -> list[str]:
    """Return list of missing or None-valued required dotted paths."""
    errors: list[str] = []
    for path in required_paths:
        try:
            val = lookup_dotted_path(config, path)
            if val is None or (isinstance(val, str) and not val.strip()):
                errors.append(f"Empty required configuration key: '{path}'")
        except KeyError:
            errors.append(f"Missing required configuration key: '{path}'")
    return errors


def flatten_config_keys(
    config: dict[str, Any], prefix: str = ""
) -> dict[str, Any]:
    """Flatten nested dictionaries into sorted `a.b.c` leaf entries."""
    out: dict[str, Any] = {}
    for k in sorted(config):
        full = f"{prefix}.{k}" if prefix else k
        val = config[k]
        if isinstance(val, dict):
            out.update(flatten_config_keys(val, prefix=full))
        else:
            out[full] = val
    return out
