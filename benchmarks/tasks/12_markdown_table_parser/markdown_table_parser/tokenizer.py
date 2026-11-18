"""Row-level cell splitter handling GFM escaped pipes and inline backtick code spans."""

from __future__ import annotations


def split_gfm_row(line: str) -> list[str]:
    """Split a GFM table row on unescaped outer `|` delimiters."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith(r"\|"):
        stripped = stripped[:-1]

    # BUG: naive `.split("|")` splits inside backtick code spans (e.g. `` `a | b` `` and
    # multi-backtick `` ``a | ` | b`` ``) AND splits on backslash-escaped `\|` pipes!
    return [cell.strip() for cell in stripped.split("|")]
