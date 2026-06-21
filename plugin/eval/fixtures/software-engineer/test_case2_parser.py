"""Failing test for case 2 (must pass after the engineer's fix; do not weaken it)."""

from __future__ import annotations

import datetime

from case2_parser import parse_date


def test_parse_date_slash() -> None:
    assert parse_date("31/12/2026") == datetime.date(2026, 12, 31)


def test_parse_date_iso() -> None:
    # Currently fails: parse_date rejects ISO-8601 input.
    assert parse_date("2026-12-31") == datetime.date(2026, 12, 31)
