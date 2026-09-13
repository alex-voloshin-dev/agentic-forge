"""Tests for the date parsing helpers (case 2)."""

from __future__ import annotations

import datetime

from case2_parser import parse_date


def test_parse_date_slash() -> None:
    assert parse_date("31/12/2026") == datetime.date(2026, 12, 31)


def test_parse_date_iso() -> None:
    assert parse_date("2026-12-31") == datetime.date(2026, 12, 31)
