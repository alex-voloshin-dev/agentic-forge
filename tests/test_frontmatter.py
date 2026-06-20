from __future__ import annotations

import pytest

from agentic_forge.frontmatter import FrontmatterError, parse


def test_parse_basic() -> None:
    fm, body = parse("---\nname: x\ndescription: y\n---\nhello\n")
    assert fm == {"name": "x", "description": "y"}
    assert body == "hello\n"


def test_parse_empty_frontmatter() -> None:
    fm, body = parse("---\n\n---\nbody")
    assert fm == {}
    assert body == "body"


def test_missing_frontmatter() -> None:
    with pytest.raises(FrontmatterError):
        parse("no frontmatter here")


def test_non_mapping_frontmatter() -> None:
    with pytest.raises(FrontmatterError):
        parse("---\n- a\n- b\n---\nbody")


def test_invalid_yaml() -> None:
    with pytest.raises(FrontmatterError):
        parse("---\nname: : :\n  - broken\n---\n")
