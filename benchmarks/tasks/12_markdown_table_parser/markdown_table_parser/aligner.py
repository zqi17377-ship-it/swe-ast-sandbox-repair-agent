"""Delimiter-row alignment specification parser (`:---`, `:---:`, `---:`)."""

from __future__ import annotations

from enum import Enum
import re

_DELIM_CELL_RE = re.compile(r"^:?-{3,}:?$")


class ColumnAlign(str, Enum):
    """GFM table column horizontal alignment."""

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    DEFAULT = "default"


def parse_delimiter_cells(cells: list[str]) -> list[ColumnAlign]:
    """Validate and parse GFM alignment markers for each table column."""
    if not cells:
        raise ValueError("Delimiter row must contain at least one column.")
    alignments: list[ColumnAlign] = []
    for raw in cells:
        tok = raw.strip()
        if not _DELIM_CELL_RE.match(tok):
            raise ValueError(f"Invalid GFM delimiter cell: {raw!r}")
        if tok.startswith(":") and tok.endswith(":"):
            alignments.append(ColumnAlign.CENTER)
        elif tok.endswith(":"):
            alignments.append(ColumnAlign.RIGHT)
        elif tok.startswith(":"):
            alignments.append(ColumnAlign.LEFT)
        else:
            alignments.append(ColumnAlign.DEFAULT)
    return alignments
