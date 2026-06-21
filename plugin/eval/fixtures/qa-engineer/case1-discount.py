"""Pricing helper (QA fixture: no tests; unguarded edge cases)."""


def discount(price, pct):
    """Return price after applying a pct percent discount."""
    return price * (1 - pct / 100)
