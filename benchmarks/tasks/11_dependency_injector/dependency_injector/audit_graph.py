"""Resolution trace recorder and dependency tree formatting helpers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ResolutionTracer:
    """Tracks active dependency stack for cycle diagnostics and audit logging."""

    _active_stack: list[str] = field(default_factory=list)
    _completed_events: list[str] = field(default_factory=list)

    def push(self, key: str) -> list[str] | None:
        """Push `key` onto stack; return cycle path if `key` is already resolving."""
        if key in self._active_stack:
            idx = self._active_stack.index(key)
            return self._active_stack[idx:] + [key]
        self._active_stack.append(key)
        return None

    def pop(self, key: str) -> None:
        """Pop `key` after factory invocation finishes or unwinds."""
        if self._active_stack and self._active_stack[-1] == key:
            self._active_stack.pop()
            self._completed_events.append(key)

    def format_history(self) -> str:
        """Return comma-separated sequence of resolved service keys."""
        return ", ".join(self._completed_events)
