"""Clamp helper (QA fixture: planted upper-bound defect for a test to surface).

Spec: clamp(value, lo, hi) returns value constrained to [lo, hi].
"""


def clamp(value, lo, hi):
    # Defect: only the lower bound is enforced; values above hi pass through.
    if value < lo:
        return lo
    return value
