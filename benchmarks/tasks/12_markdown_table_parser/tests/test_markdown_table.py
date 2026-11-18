"""Tests for GFM table row splitting with escaped pipes and single/double-backtick code spans."""

from __future__ import annotations

from markdown_table_parser import parse_markdown_table, split_gfm_row


def test_escaped_pipe_outside_code_span_is_unescaped_and_not_split() -> None:
    md = "| Expr | Meaning |\n| :--- | :--- |\n| a \\| b | bitwise or |"
    tbl = parse_markdown_table(md)
    assert tbl.rows == [["a | b", "bitwise or"]]


def test_raw_pipe_inside_single_backtick_code_span_is_preserved() -> None:
    row = "| `x | y` | union type |"
    assert split_gfm_row(row) == ["`x | y`", "union type"]


def test_escaped_pipe_inside_code_span_retains_literal_backslash_per_gfm() -> None:
    # Per CommonMark/GFM spec: inside inline code spans, backslashes are literal characters,
    # EXCEPT GFM table cell splitting still treats `\|` as escaped delimiter ORWait:
    # Actually in GFM tables, `\|` inside `` `re: a\|b` `` must preserve literal `` `re: a\|b` ``!
    row = r"| `re: a\|b` | pattern |"
    assert split_gfm_row(row) == [r"`re: a\|b`", "pattern"]


def test_double_backtick_code_span_containing_single_backtick_and_pipe() -> None:
    row = "| ``a` | `b`` | shell example |"
    assert split_gfm_row(row) == ["``a` | `b``", "shell example"]
