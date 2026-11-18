"""Tests for KeysetPaginator boundary deduplication, tie-breaking, and exact-multiple final page."""

from __future__ import annotations

from pagination_cursor import KeysetPaginator, RecordItem


def _sample_items(n: int) -> list[RecordItem]:
    return [
        RecordItem(item_id=f"item-{i:02d}", sort_value=(i // 2) * 10)
        for i in range(1, n + 1)
    ]


def test_cursor_walk_has_no_duplicates_across_tied_sort_values() -> None:
    items = _sample_items(5)
    paginator = KeysetPaginator()

    collected: list[str] = []
    cursor: str | None = None
    finished = False
    for _ in range(6):
        page = paginator.paginate(items, limit=2, after_cursor=cursor)
        collected.extend(r.item_id for r in page.items)
        if not page.has_more:
            assert page.next_cursor is None
            finished = True
            break
        cursor = page.next_cursor

    assert finished is True, "Pagination failed to terminate within expected page count"
    assert collected == ["item-01", "item-02", "item-03", "item-04", "item-05"]


def test_exact_multiple_total_count_sets_has_more_false_on_last_page() -> None:
    items = _sample_items(4)
    paginator = KeysetPaginator()

    p1 = paginator.paginate(items, limit=2)
    assert [r.item_id for r in p1.items] == ["item-01", "item-02"]
    assert p1.has_more is True
    assert p1.next_cursor is not None

    p2 = paginator.paginate(items, limit=2, after_cursor=p1.next_cursor)
    assert [r.item_id for r in p2.items] == ["item-03", "item-04"]
    assert p2.has_more is False
    assert p2.next_cursor is None


def test_empty_dataset_returns_no_cursor() -> None:
    paginator = KeysetPaginator()
    page = paginator.paginate([], limit=5)
    assert page.items == []
    assert page.has_more is False
    assert page.next_cursor is None
