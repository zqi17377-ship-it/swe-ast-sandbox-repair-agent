"""Custom exception hierarchy for circuit breaker fast-fail protection."""

from __future__ import annotations


class CircuitBreakerError(RuntimeError):
    """Base error raised by resilience guards."""


class CircuitOpenError(CircuitBreakerError):
    """Raised when a call is rejected because the circuit is OPEN or probe-saturated."""

    def __init__(self, service_name: str, retry_after_sec: float = 0.0) -> None:
        self.service_name = service_name
        self.retry_after_sec = max(0.0, retry_after_sec)
        super().__init__(
            f"Circuit for '{service_name}' is unavailable; retry after {self.retry_after_sec:.2f}s."
        )
