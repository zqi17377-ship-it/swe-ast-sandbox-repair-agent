"""Diagnostic SQL formatting, parameter redaction, and query complexity helpers."""

from __future__ import annotations

from typing import Any

from sql_query_builder.ast_nodes import CompiledQuery

_SENSITIVE_KEYS = ("password", "secret", "token", "ssn", "api_key")


def redact_query_params(
    query: CompiledQuery, mask: str = "***REDACTED***"
) -> dict[str, Any]:
    """Return a copy of bound parameters with sensitive values masked for logging."""
    sanitized: dict[str, Any] = {}
    for key, val in query.params.items():
        lowered = key.lower()
        if any(marker in lowered for marker in _SENSITIVE_KEYS):
            sanitized[key] = mask
        elif isinstance(val, str) and len(val) > 64:
            sanitized[key] = f"{val[:61]}..."
        else:
            sanitized[key] = val
    return sanitized


def pretty_format_sql(query: CompiledQuery) -> str:
    """Insert line breaks before major SQL keywords for human inspection."""
    sql = query.sql
    for kw in ("FROM ", "INNER JOIN ", "LEFT JOIN ", "WHERE ", "ORDER BY ", "LIMIT "):
        sql = sql.replace(f" {kw}", f"\n{kw}")
    return sql


def estimate_bind_load(query: CompiledQuery, max_params: int = 999) -> float:
    """Compute fraction of dialect bind-parameter ceiling utilized by `query`."""
    if max_params <= 0:
        return 1.0
    return round(len(query.params) / max_params, 4)
