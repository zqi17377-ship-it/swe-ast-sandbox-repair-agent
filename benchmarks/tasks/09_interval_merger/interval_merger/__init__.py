"""Closed & Half-Open Interval Timeline Merger Package."""

from interval_merger.models import Interval
from interval_merger.timeline_merger import merge_intervals

__all__ = ["Interval", "merge_intervals"]
