"""Date parsing helpers (software-engineer eval fixture, case 2)."""

from __future__ import annotations

import datetime


def parse_date(text: str) -> datetime.date:
    day, month, year = text.split("/")
    return datetime.date(int(year), int(month), int(day))
