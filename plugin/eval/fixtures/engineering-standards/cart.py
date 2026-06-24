"""A tiny shopping-cart total (engineering-standards Tier-2 eval fixture target)."""

from __future__ import annotations


def total(prices: list[float]) -> float:
    """Sum the item prices."""
    return sum(prices)
