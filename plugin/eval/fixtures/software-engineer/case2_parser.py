"""Date parsing under test (case 2). The engineer must fix parse_date.

parse_date currently accepts only the "DD/MM/YYYY" format and raises on ISO-8601
("YYYY-MM-DD") input, which makes test_parse_date fail. Fix the implementation so both the
existing slash format and ISO-8601 are accepted, without weakening the test.
"""

from __future__ import annotations

import datetime


def parse_date(text: str) -> datetime.date:
    day, month, year = text.split("/")
    return datetime.date(int(year), int(month), int(day))
