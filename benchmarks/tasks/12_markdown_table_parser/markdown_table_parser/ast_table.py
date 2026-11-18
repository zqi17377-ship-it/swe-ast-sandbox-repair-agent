"""Structured AST representation and block parser for GFM Markdown tables."""

from __future__ import annotations

from dataclasses import dataclass

from markdown_table_parser.aligner import ColumnAlign, parse_delimiter_cells
from markdown_table_parser.tokenizer import split_gfm_row


@dataclass(frozen=True)
class MarkdownTable:
    """Parsed GFM table header, column alignments, and normalized body rows."""

    headers: list[str]
    alignments: list[ColumnAlign]
    rows: list[list[str]]


def parse_markdown_table(markdown_text: str) -> MarkdownTable:
    """Parse a multi-line GFM table block into `MarkdownTable`."""
    non_empty = [ln for ln in markdown_text.strip().splitlines() if ln.strip()]
    if len(non_empty) < 2:
        raise ValueError("A GFM table requires at least header and delimiter rows.")

    headers = split_gfm_row(non_empty[0])
    alignments = parse_delimiter_cells(split_gfm_row(non_empty[1]))
    if len(headers) != len(alignments):
        raise ValueError(
            f"Header column count ({len(headers)}) != delimiter count ({len(alignments)})."
        )

    col_count = len(headers)
    body_rows: list[list[str]] = []
    for raw_line in non_empty[2:]:
        cells = split_gfm_row(raw_line)
        if len(cells) < col_count:
            cells = cells + [""] * (col_count - len(cells))
        elif len(cells) > col_count:
            cells = cells[:col_count]
        body_rows.append(cells)

    return MarkdownTable(headers=headers, alignments=alignments, rows=body_rows)
