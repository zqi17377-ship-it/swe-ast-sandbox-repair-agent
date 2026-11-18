"""Deterministic banker's-rounding foreign exchange minor-unit conversion."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN


class FXRateTable:
    """Stores spot FX rates quoted against USD and converts minor units."""

    def __init__(self) -> None:
        self._rates_to_usd: dict[str, Decimal] = {
            "USD": Decimal("1.000000"),
            "EUR": Decimal("1.085000"),
            "GBP": Decimal("1.270000"),
            "JPY": Decimal("0.006650"),
        }

    def set_rate(self, currency: str, rate_to_usd: str) -> None:
        val = Decimal(rate_to_usd)
        if val <= 0:
            raise ValueError("FX rate must be positive.")
        self._rates_to_usd[currency.upper()] = val

    def convert_to_usd_cents(self, minor_units: int, currency: str) -> int:
        code = currency.upper()
        if code not in self._rates_to_usd:
            raise KeyError(f"Unsupported currency code: {code}")
        raw = Decimal(minor_units) * self._rates_to_usd[code]
        return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))
