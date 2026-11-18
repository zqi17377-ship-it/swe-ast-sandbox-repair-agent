"""Tests for largest-remainder penny conservation and invoice/credit-reversal symmetry."""

from __future__ import annotations

from ledger_reconciler import LedgerReconciler, allocate_largest_remainder


def test_largest_remainder_sum_equals_exact_total() -> None:
    shares = allocate_largest_remainder(100, [1, 1, 1])
    assert shares == [34, 33, 33]
    assert sum(shares) == 100


def test_negative_allocation_mirrors_positive_shares() -> None:
    pos = allocate_largest_remainder(101, [2, 1, 1])
    neg = allocate_largest_remainder(-101, [2, 1, 1])
    assert sum(neg) == -101
    assert [p + n for p, n in zip(pos, neg)] == [0, 0, 0]


def test_invoice_and_full_credit_reversal_zero_all_cost_center_balances() -> None:
    rec = LedgerReconciler("USD")
    centers = ["cc_eng", "cc_sales", "cc_ops"]
    weights = [3, 2, 2]

    inv_lines = rec.post_invoice(gross_cents=1003, fee_bps=290, cost_centers=centers, weights=weights)
    assert sum(ln.gross_cents for ln in inv_lines) == 1003

    rec.post_credit_reversal(gross_cents=1003, fee_bps=290, cost_centers=centers, weights=weights)
    balances = rec.snapshot_balances()
    for cc, (net_c, fee_c, gross_c) in balances.items():
        assert (net_c, fee_c, gross_c) == (0, 0, 0), f"Non-zero residual in {cc}: {(net_c, fee_c, gross_c)}"
