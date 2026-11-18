"""Proportional minor-unit allocation using Hamilton's largest-remainder method."""

from __future__ import annotations


def allocate_largest_remainder(amount_cents: int, weights: list[int]) -> list[int]:
    """Split `amount_cents` across positive `weights` so shares sum to `amount_cents`."""
    if not weights:
        return []
    if any(w <= 0 for w in weights):
        raise ValueError("All allocation weights must be strictly positive.")

    total_weight = sum(weights)
    # BUG: floors each share via `//` and discards the remainder pennies completely,
    # AND Python's floor division on negative `amount_cents` rounds toward -infinity!
    return [(amount_cents * w) // total_weight for w in weights]
