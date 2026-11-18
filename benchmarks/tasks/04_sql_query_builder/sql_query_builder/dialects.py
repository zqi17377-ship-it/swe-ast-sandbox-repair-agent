"""SQL identifier validation and dialect quoting rules."""

from __future__ import annotations

import re
from dataclasses import dataclass

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$")


@dataclass(frozen=True)
class DialectConfig:
    """Configuration for target SQL engine syntax conventions."""

    name: str = "sqlite"
    quote_char: str = '"'
    max_bind_params: int = 999


def validate_identifier(identifier: str) -> str:
    """Ensure SQL table or column identifier contains no injection characters."""
    cleaned = identifier.strip()
    if not _IDENTIFIER_RE.match(cleaned):
        raise ValueError(f"Unsafe or invalid SQL identifier: {identifier!r}")
    return cleaned


def quote_identifier(identifier: str, dialect: DialectConfig | None = None) -> str:
    """Quote a single or table-qualified SQL identifier using dialect delimiters."""
    cfg = dialect or DialectConfig()
    valid = validate_identifier(identifier)
    q = cfg.quote_char
    return ".".join(f"{q}{segment}{q}" for segment in valid.split("."))
