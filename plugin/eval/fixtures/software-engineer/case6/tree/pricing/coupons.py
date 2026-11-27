"""Coupon codes.

Invariant: a coupon is single-use per customer. Once a customer has redeemed a coupon, any
further attempt by that customer to redeem the same coupon is rejected.
"""

from __future__ import annotations

COUPONS: dict[str, int] = {"SAVE10": 10, "WELCOME5": 5}  # code -> percent off


class CouponError(ValueError):
    """An unknown or already-redeemed coupon."""


class CouponBook:
    def __init__(self) -> None:
        self._redeemed: set[tuple[str, str]] = set()  # (customer_id, code)

    def apply_coupon(self, customer_id: str, code: str, amount_cents: int) -> int:
        """Return ``amount_cents`` after the coupon's discount and mark it redeemed."""
        if code not in COUPONS:
            raise CouponError(f"unknown coupon {code!r}")
        if (customer_id, code) in self._redeemed:
            raise CouponError(f"coupon {code!r} already redeemed")
        self._redeemed.add((customer_id, code))
        return amount_cents - amount_cents * COUPONS[code] // 100
