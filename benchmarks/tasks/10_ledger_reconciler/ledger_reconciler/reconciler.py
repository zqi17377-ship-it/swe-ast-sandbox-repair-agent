"""Invoice and credit-note sub-ledger reconciliation engine."""

from __future__ import annotations

from ledger_reconciler.accounts import JournalLine, LedgerAccount
from ledger_reconciler.allocator import allocate_largest_remainder


class LedgerReconciler:
    """Posts multi-center invoices and reversals while maintaining zero-penny drift."""

    def __init__(self, currency: str = "USD") -> None:
        self.currency = currency
        self._accounts: dict[str, LedgerAccount] = {}

    def _account(self, cost_center: str) -> LedgerAccount:
        if cost_center not in self._accounts:
            self._accounts[cost_center] = LedgerAccount(cost_center, self.currency)
        return self._accounts[cost_center]

    def post_invoice(
        self,
        gross_cents: int,
        fee_bps: int,
        cost_centers: list[str],
        weights: list[int],
    ) -> list[JournalLine]:
        """Allocate gross and fee cents across `cost_centers` and post journal lines."""
        if gross_cents < 0:
            raise ValueError("Invoice gross_cents must be non-negative.")
        if len(cost_centers) != len(weights):
            raise ValueError("cost_centers and weights length mismatch.")

        total_fee = (gross_cents * fee_bps + 5000) // 10000
        total_net = gross_cents - total_fee
        net_shares = allocate_largest_remainder(total_net, weights)
        fee_shares = allocate_largest_remainder(total_fee, weights)

        posted: list[JournalLine] = []
        for cc, n_val, f_val in zip(cost_centers, net_shares, fee_shares):
            line = JournalLine(cc, net_cents=n_val, fee_cents=f_val, currency=self.currency)
            self._account(cc).post(line)
            posted.append(line)
        return posted

    def post_credit_reversal(
        self,
        gross_cents: int,
        fee_bps: int,
        cost_centers: list[str],
        weights: list[int],
    ) -> list[JournalLine]:
        """Post a credit-note reversal of `gross_cents` across `cost_centers`."""
        if gross_cents < 0:
            raise ValueError("gross_cents magnitude must be non-negative.")
        # Subtle cross-module bug: computes negative fee via floor division `(-gross * bps + 5000) // 10000`
        # AND allocates gross first instead of `(net, fee)` independently, causing 1-cent gross/fee skew!
        signed_gross = -gross_cents
        total_fee = (signed_gross * fee_bps + 5000) // 10000
        gross_shares = allocate_largest_remainder(signed_gross, weights)
        fee_shares = allocate_largest_remainder(total_fee, weights)

        posted: list[JournalLine] = []
        for cc, g_val, f_val in zip(cost_centers, gross_shares, fee_shares):
            line = JournalLine(
                cc, net_cents=g_val - f_val, fee_cents=f_val, currency=self.currency
            )
            self._account(cc).post(line)
            posted.append(line)
        return posted

    def snapshot_balances(self) -> dict[str, tuple[int, int, int]]:
        """Return `{cost_center: (net_cents, fee_cents, gross_cents)}`."""
        return {
            cc: (acc.net_balance_cents, acc.fee_balance_cents, acc.gross_balance_cents)
            for cc, acc in sorted(self._accounts.items())
        }
