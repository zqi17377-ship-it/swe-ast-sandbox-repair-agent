"""Chart-of-accounts entries and balanced double-entry journal models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class JournalLine:
    """Single minor-unit (cents) posting against a sub-ledger cost center."""

    cost_center: str
    net_cents: int
    fee_cents: int
    currency: str = "USD"

    @property
    def gross_cents(self) -> int:
        return self.net_cents + self.fee_cents


@dataclass
class LedgerAccount:
    """Tracks cumulative posted lines and running net/fee balances per cost center."""

    cost_center: str
    currency: str = "USD"
    _lines: list[JournalLine] = field(default_factory=list)

    def post(self, line: JournalLine) -> None:
        if line.currency != self.currency:
            raise ValueError(
                f"Currency mismatch: account={self.currency}, line={line.currency}"
            )
        self._lines.append(line)

    @property
    def net_balance_cents(self) -> int:
        return sum(ln.net_cents for ln in self._lines)

    @property
    def fee_balance_cents(self) -> int:
        return sum(ln.fee_cents for ln in self._lines)

    @property
    def gross_balance_cents(self) -> int:
        return sum(ln.gross_cents for ln in self._lines)
