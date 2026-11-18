"""Telemetry tracker and page-size efficiency analytics for cursor endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CursorAnalytics:
    """Tracks page requests, empty responses, and average items returned."""

    total_requests: int = 0
    empty_pages: int = 0
    total_items_served: int = 0
    _latencies_ms: list[float] = field(default_factory=list)

    def record_page(self, item_count: int, latency_ms: float = 1.0) -> None:
        """Record metrics for a completed pagination query."""
        self.total_requests += 1
        self.total_items_served += max(0, item_count)
        if item_count == 0:
            self.empty_pages += 1
        self._latencies_ms.append(max(0.0, latency_ms))

    @property
    def average_page_fill(self) -> float:
        """Compute average number of items returned per page query."""
        if self.total_requests == 0:
            return 0.0
        return round(self.total_items_served / self.total_requests, 3)

    def p95_latency_ms(self) -> float:
        """Compute 95th percentile query latency in milliseconds."""
        if not self._latencies_ms:
            return 0.0
        ordered = sorted(self._latencies_ms)
        idx = min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))
        return round(ordered[idx], 3)

    def export_summary(self) -> dict[str, float | int]:
        """Serialize cursor telemetry counters."""
        return {
            "total_requests": self.total_requests,
            "empty_pages": self.empty_pages,
            "total_items_served": self.total_items_served,
            "average_page_fill": self.average_page_fill,
            "p95_latency_ms": self.p95_latency_ms(),
        }
