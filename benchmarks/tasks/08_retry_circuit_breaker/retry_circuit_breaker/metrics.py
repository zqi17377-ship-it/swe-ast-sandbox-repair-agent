"""Sliding window success/failure rate tracker for downstream endpoints."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class RollingHealthWindow:
    """Maintains bounded boolean call outcomes to monitor downstream error rates."""

    capacity: int = 50
    _outcomes: deque[bool] = field(default_factory=deque)

    def record(self, succeeded: bool) -> None:
        """Record True for a healthy call or False for a downstream failure."""
        self._outcomes.append(succeeded)
        while len(self._outcomes) > self.capacity:
            self._outcomes.popleft()

    @property
    def sample_size(self) -> int:
        return len(self._outcomes)

    @property
    def failure_rate(self) -> float:
        """Return failure ratio in [0.0, 1.0] across buffered calls."""
        if not self._outcomes:
            return 0.0
        failures = sum(1 for ok in self._outcomes if not ok)
        return round(failures / len(self._outcomes), 4)

    def is_degraded(self, min_samples: int = 10, threshold: float = 0.5) -> bool:
        """Return True when enough samples exist and failure rate meets threshold."""
        if len(self._outcomes) < min_samples:
            return False
        return self.failure_rate >= threshold

    def reset(self) -> None:
        """Clear all recorded window samples."""
        self._outcomes.clear()
