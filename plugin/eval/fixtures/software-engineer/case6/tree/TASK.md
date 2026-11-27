# Task T2 (from plan.md): case-insensitive coupon codes

Customers type coupon codes in any case, and support keeps getting "my code does not work"
tickets for `save10`. `CouponBook.apply_coupon` must treat a code the same regardless of
case: `save10`, `Save10` and `SAVE10` are one coupon.

Scope: the coupon module (`pricing/coupons.py`) and its tests (`tests/test_coupons.py`)
only. Run the test suite with `python -m pytest -q`. Report the files you touched and the
tests you added.
