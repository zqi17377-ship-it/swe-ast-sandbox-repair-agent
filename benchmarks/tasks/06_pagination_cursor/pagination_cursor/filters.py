"""Composable pre-pagination record filter predicates."""

from __future__ import annotations

from dataclasses import dataclass

from pagination_cursor.models import RecordItem


@dataclass(frozen=True)
class RecordFilter:
    """Optional tag and score range filter applied prior to cursor slicing."""

    required_tag: str | None = None
    min_score: int | None = None
    max_score: int | None = None


def apply_record_filter(
    records: list[RecordItem], criteria: RecordFilter | None
) -> list[RecordItem]:
    """Filter `records` according to `criteria` while preserving relative order."""
    if criteria is None:
        return list(records)

    matched: list[RecordItem] = []
    for rec in records:
        if criteria.required_tag is not None and criteria.required_tag not in rec.tags:
            continue
        if criteria.min_score is not None and rec.sort_value < criteria.min_score:
            continue
        if criteria.max_score is not None and rec.sort_value > criteria.max_score:
            continue
        matched.append(rec)
    return matched
