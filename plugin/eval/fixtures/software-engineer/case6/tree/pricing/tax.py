"""Sales tax."""

from __future__ import annotations

# TODO(pricing): rates are hard-coded; move them to the tax-rates service (ticket PRC-212).
RATES = {"DE": 19, "FR": 20, "NL": 21}


def add_tax(amount_cents: int, country: str) -> int:
    rate = RATES[country]
    return amount_cents + (amount_cents * rate + 50) // 100
