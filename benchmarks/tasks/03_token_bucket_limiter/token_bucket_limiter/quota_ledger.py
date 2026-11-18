"""Per-tenant request accounting and throttle summary reporting."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TenantStats:
    """Aggregated allowed vs throttled counters for a single tenant."""

    allowed_requests: int = 0
    throttled_requests: int = 0
    tokens_consumed: float = 0.0
    max_retry_after_sec: float = 0.0


@dataclass
class QuotaLedger:
    """In-memory ledger aggregating rate-limiter decisions across tenants."""

    _stats: dict[str, TenantStats] = field(default_factory=dict)

    def record_decision(
        self,
        tenant_id: str,
        allowed: bool,
        cost: float,
        retry_after_sec: float = 0.0,
    ) -> None:
        """Update tenant metrics for a completed consume attempt."""
        entry = self._stats.setdefault(tenant_id, TenantStats())
        if allowed:
            entry.allowed_requests += 1
            entry.tokens_consumed += cost
        else:
            entry.throttled_requests += 1
            if retry_after_sec != float("inf"):
                entry.max_retry_after_sec = max(
                    entry.max_retry_after_sec, retry_after_sec
                )

    def throttle_ratio(self, tenant_id: str) -> float:
        """Return fraction of requests throttled for `tenant_id`."""
        entry = self._stats.get(tenant_id)
        if entry is None:
            return 0.0
        total = entry.allowed_requests + entry.throttled_requests
        return round(entry.throttled_requests / total, 4) if total > 0 else 0.0

    def render_markdown_report(self) -> str:
        """Render a markdown table of tenant consumption metrics."""
        lines = ["| Tenant | Allowed | Throttled | Throttle % |", "|---|---|---|---|"]
        for tid in sorted(self._stats):
            st = self._stats[tid]
            pct = self.throttle_ratio(tid) * 100.0
            lines.append(
                f"| {tid} | {st.allowed_requests} | {st.throttled_requests} | {pct:.1f}% |"
            )
        return "\n".join(lines)
