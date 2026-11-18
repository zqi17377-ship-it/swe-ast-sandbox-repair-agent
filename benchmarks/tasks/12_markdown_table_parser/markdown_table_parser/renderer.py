"""HTML and normalized Markdown emitters for `MarkdownTable` AST nodes."""

from __future__ import annotations

import html

from markdown_table_parser.aligner import ColumnAlign
from markdown_table_parser.ast_table import MarkdownTable


def _align_attr(align: ColumnAlign) -> str:
    if align == ColumnAlign.DEFAULT:
        return ""
    return f' style="text-align:{align.value}"'


def render_html_table(table: MarkdownTable) -> str:
    """Render a `MarkdownTable` into escaped semantic HTML."""
    out = ["<table>", "  <thead>", "    <tr>"]
    for h_text, align in zip(table.headers, table.alignments):
        out.append(f"      <th{_align_attr(align)}>{html.escape(h_text)}</th>")
    out.extend(["    </tr>", "  </thead>", "  <tbody>"])
    for row in table.rows:
        out.append("    <tr>")
        for cell, align in zip(row, table.alignments):
            out.append(f"      <td{_align_attr(align)}>{html.escape(cell)}</td>")
        out.append("    </tr>")
    out.extend(["  </tbody>", "</table>"])
    return "\n".join(out)
