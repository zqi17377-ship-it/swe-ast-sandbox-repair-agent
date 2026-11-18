"""Placeholder interpolation (`${VAR:-default}`) across nested configuration trees."""

from __future__ import annotations

import re
from typing import Any

_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def interpolate_env_vars(
    config: dict[str, Any], env_map: dict[str, str]
) -> dict[str, Any]:
    """Resolve `${VAR:-fallback}` string templates recursively using `env_map`."""

    def _transform(value: Any) -> Any:
        if isinstance(value, str):
            def _sub(match: re.Match[str]) -> str:
                var_name = match.group(1)
                default_val = match.group(2)
                if var_name in env_map:
                    return env_map[var_name]
                if default_val is not None:
                    return default_val
                raise KeyError(f"Missing required environment variable: {var_name}")

            return _PLACEHOLDER_RE.sub(_sub, value)
        if isinstance(value, dict):
            return {k: _transform(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_transform(item) for item in value]
        return value

    return _transform(config)
