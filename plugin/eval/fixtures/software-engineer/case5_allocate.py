"""Money allocation helpers (software-engineer eval fixture, case 5)."""

from __future__ import annotations


def allocate(total_cents: int, weights: list[int]) -> list[int]:
    """Split ``total_cents`` across ``weights`` in proportion, one part per weight.

    ``total_cents`` is >= 0 and every weight is a positive int.

    Invariants (callers rely on both; invoices are reconciled against them):

    1. The parts always sum to exactly ``total_cents`` -- no cent is lost or created.
    2. Every part is within one cent of its exact proportional share
       ``total_cents * weight / sum(weights)``: it is that share rounded down or rounded up,
       never further off.
    """
    whole = sum(weights)
    return [total_cents * w // whole for w in weights]
