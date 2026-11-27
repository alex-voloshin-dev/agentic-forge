"""Tests for the money allocation helpers (case 5)."""

from __future__ import annotations

from case5_allocate import allocate


def test_allocate_even_split() -> None:
    assert allocate(90, [1, 1, 1]) == [30, 30, 30]


def test_allocate_uneven_split_keeps_every_cent() -> None:
    assert allocate(100, [1, 1, 1]) == [34, 33, 33]
