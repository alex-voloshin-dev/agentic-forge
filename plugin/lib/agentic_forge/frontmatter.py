"""Parse YAML frontmatter from a SKILL.md (or any markdown) file."""

from __future__ import annotations

import re
from typing import Any

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
        import yaml  # lazy: a guardrail hook may run under a python3 without PyYAML installed
    except ImportError as exc:
        raise FrontmatterError("PyYAML is not installed; cannot parse frontmatter") from exc

    class _NoAliases(yaml.SafeLoader):
        """Refuses a YAML alias. Frontmatter has no need of one, and a few lines of them expand to
        more than memory holds (ADR 0104)."""

        def compose_node(self, parent: Any, index: Any) -> Any:
            if self.check_event(yaml.events.AliasEvent):
                raise yaml.YAMLError("an alias is not allowed in frontmatter")
            return super().compose_node(parent, index)

    try:
        data = yaml.load(match.group(1), Loader=_NoAliases)
    except yaml.YAMLError as exc:
        raise FrontmatterError(f"invalid YAML in frontmatter: {exc}") from exc
    # PyYAML raises others on some input: KeyError on a bad `!!bool`, ValueError on an impossible
    # date, RecursionError on nesting. Their text can repeat the file's, so none of it goes on.
    except Exception as exc:
        reason = f"frontmatter could not be parsed ({type(exc).__name__})"
        raise FrontmatterError(reason) from None

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise FrontmatterError("frontmatter must be a mapping")

    return data, match.group(2)
