"""Parse YAML frontmatter from a SKILL.md (or any markdown) file."""

from __future__ import annotations

import re
from typing import Any

import yaml

__all__ = ["FrontmatterError", "parse"]

_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)\Z", re.DOTALL)


class FrontmatterError(ValueError):
    """Raised when frontmatter is missing or malformed."""


def parse(text: str) -> tuple[dict[str, Any], str]:
    """Split markdown text into (frontmatter_mapping, body).

    Raises FrontmatterError if the leading YAML frontmatter block is missing or is
    not a mapping.
    """
    match = _FRONTMATTER.match(text)
    if match is None:
        raise FrontmatterError(
            "missing or malformed YAML frontmatter (expected leading '---' block)"
        )

    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise FrontmatterError(f"invalid YAML in frontmatter: {exc}") from exc

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise FrontmatterError("frontmatter must be a mapping")

    return data, match.group(2)
