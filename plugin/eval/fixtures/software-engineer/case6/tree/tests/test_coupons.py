from __future__ import annotations

import pytest

from pricing.coupons import CouponBook, CouponError


def test_applies_known_coupon() -> None:
    assert CouponBook().apply_coupon("c1", "SAVE10", 2000) == 1800


def test_rejects_unknown_coupon() -> None:
    with pytest.raises(CouponError):
        CouponBook().apply_coupon("c1", "NOPE", 2000)


def test_coupon_is_single_use_per_customer() -> None:
    book = CouponBook()
    book.apply_coupon("c1", "SAVE10", 2000)
    with pytest.raises(CouponError):
        book.apply_coupon("c1", "SAVE10", 2000)
    assert book.apply_coupon("c2", "SAVE10", 2000) == 1800
