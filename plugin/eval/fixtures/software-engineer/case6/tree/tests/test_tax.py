from __future__ import annotations

from pricing.format import euros
from pricing.tax import add_tax


def test_add_tax_rounds_half_up() -> None:
    assert add_tax(1000, "DE") == 1190


def test_euros() -> None:
    assert euros(1190) == "EUR 11.90"
