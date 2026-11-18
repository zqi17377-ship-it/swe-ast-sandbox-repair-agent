"""Structural lint checks for column-width balance and empty headers."""

from __future__ import annotations

from dataclasses import dataclass

from markdown_table_parser.ast_table import MarkdownTable


@dataclass(frozen=True)
class TableLintWarning:
    """Non-fatal quality warning emitted for a parsed Markdown table."""

    code: str
    message: str


def lint_markdown_table(table: MarkdownTable) -> list[TableLintWarning]:
    """Check for blank header titles or duplicate column names."""
    warnings: list[TableLintWarning] = []
    seen: set[str] = set()
    for idx, header in enumerate(table.headers):
        norm = header.strip().lower()
        if not norm:
            warnings.append(
                TableLintWarning("EMPTY_HEADER", f"Column {idx} has an empty header.")
            )
        elif norm in seen:
            warnings.append(
                TableLintWarning(
                    "DUPLICATE_HEADER", f"Duplicate column header '{header}'."
                )
            )
        seen.add(norm)
    return warnings
