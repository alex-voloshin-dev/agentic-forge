from cart import total


def test_total_sums_prices() -> None:
    assert total([1.0, 2.0, 3.0]) == 6.0
