"""Deterministic keyset cursor paginator with tie-breaking composite keys."""

from __future__ import annotations

from pagination_cursor.audit_cursor import CursorAnalytics
from pagination_cursor.codec import decode_cursor, encode_cursor
from pagination_cursor.filters import RecordFilter, apply_record_filter
from pagination_cursor.models import PageResult, RecordItem


class KeysetPaginator:
    """Serves duplicate-free pages ordered by ascending `(sort_value, item_id)`."""

    def __init__(self, secret: str = "cursor-v1") -> None:
        self.secret = secret
        self.analytics = CursorAnalytics()

    def paginate(
        self,
        records: list[RecordItem],
        limit: int = 10,
        after_cursor: str | None = None,
        criteria: RecordFilter | None = None,
    ) -> PageResult:
        """Return up to `limit` records strictly after `after_cursor`."""
        if limit <= 0:
            raise ValueError("limit must be positive.")

        filtered = apply_record_filter(records, criteria)
        ordered = sorted(filtered, key=lambda r: r.sort_tuple)

        if after_cursor is not None:
            token = decode_cursor(after_cursor, secret=self.secret)
            boundary = (token.sort_value, token.item_id)
            # BUG 1: uses `>=` instead of strict `>`, duplicating boundary item on next page!
            ordered = [rec for rec in ordered if rec.sort_tuple >= boundary]

        # BUG 2: slices `ordered[:limit]` without `limit + 1` lookahead, reporting `has_more=True`
        # even when `len(ordered) == limit` (exact final page)!
        page_items = ordered[:limit]
        has_more = len(page_items) == limit
        next_cursor = (
            encode_cursor(
                page_items[-1].sort_value,
                page_items[-1].item_id,
                secret=self.secret,
            )
            if has_more and page_items
            else None
        )
        self.analytics.record_page(len(page_items))
        return PageResult(
            items=page_items,
            next_cursor=next_cursor,
            has_more=has_more,
        )
