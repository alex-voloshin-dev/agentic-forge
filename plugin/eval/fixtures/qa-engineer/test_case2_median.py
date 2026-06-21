"""Existing tests for median (QA fixture: happy path only — must be preserved, not weakened)."""

from case2_median import median


def test_median_odd():
    assert median([3, 1, 2]) == 2
