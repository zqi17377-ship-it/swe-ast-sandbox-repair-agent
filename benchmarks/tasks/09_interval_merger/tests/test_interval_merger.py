"""Tests for merge_intervals adjacent vs strict-overlap mode and caller list immutability."""

from __future__ import annotations

from interval_merger import Interval, merge_intervals


def test_merge_overlapping_and_adjacent_when_enabled() -> None:
    items = [Interval(1, 5), Interval(5, 8), Interval(10, 12)]
    assert merge_intervals(items, merge_adjacent=True) == [
        Interval(1, 8),
        Interval(10, 12),
    ]


def test_strict_overlap_mode_keeps_touching_intervals_separate() -> None:
    items = [Interval(1, 5), Interval(5, 8), Interval(7, 10)]
    # [1, 5) and [5, 8) only touch at 5 -> keep separate; [5, 8) and [7, 10) overlap -> [5, 10)
    assert merge_intervals(items, merge_adjacent=False) == [
        Interval(1, 5),
        Interval(5, 10),
    ]


def test_does_not_mutate_caller_unsorted_input_list() -> None:
    original = [Interval(10, 15), Interval(1, 4), Interval(3, 6)]
    snapshot = list(original)

    merged = merge_intervals(original, merge_adjacent=True)
    assert merged == [Interval(1, 6), Interval(10, 15)]
    assert original == snapshot, "merge_intervals must not sort caller's list in place!"


def test_empty_and_single_element_inputs() -> None:
    assert merge_intervals([]) == []
    assert merge_intervals([Interval(2, 2)], merge_adjacent=False) == [Interval(2, 2)]
