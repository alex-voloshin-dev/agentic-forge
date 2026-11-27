"""Display formatting for amounts."""

from __future__ import annotations

import os


def euros(amount_cents: int) -> str:
    return "EUR %d.%02d" % (amount_cents // 100, amount_cents % 100)
