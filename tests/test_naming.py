from __future__ import annotations

import pytest

from agentic_forge import naming


@pytest.mark.parametrize("name", ["pdf-processing", "data-analysis", "code-review", "a", "x9"])
def test_valid_names(name: str) -> None:
    assert naming.validate_name(name) == []
    assert naming.is_valid_name(name)


@pytest.mark.parametrize(
    "name",
    ["PDF-Processing", "-pdf", "pdf-", "pdf--processing", "pdf_processing", "péf", ""],
)
def test_invalid_names(name: str) -> None:
    assert naming.validate_name(name) != []
    assert not naming.is_valid_name(name)


def test_name_too_long() -> None:
    assert naming.validate_name("a" * 65) != []
    assert naming.validate_name("a" * 64) == []


def test_name_must_match_dir() -> None:
    assert naming.validate_name("foo", dir_name="bar") != []
    assert naming.validate_name("foo", dir_name="foo") == []
