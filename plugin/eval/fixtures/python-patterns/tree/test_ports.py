from __future__ import annotations

import pytest

from ports import parse_port


def test_parse_port_accepts_a_registered_port() -> None:
    assert parse_port("8080") == 8080


def test_parse_port_rejects_garbage_and_out_of_range() -> None:
    with pytest.raises(ValueError):
        parse_port("http")
    with pytest.raises(ValueError):
        parse_port("70000")
