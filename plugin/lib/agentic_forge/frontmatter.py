"""Parse YAML frontmatter from a SKILL.md (or any markdown) file.

The header must open the text. One opt-in exception, for handoff artifacts only (ADR 0112): with
``allow_title=True`` a single ATX H1 line (``# `` and some text), with blank lines around it, may
come before the header, for a repository whose documents must open with a title.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["FrontmatterError", "parse", "split_title"]

_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)\Z", re.DOTALL)
# Blank lines, one `# Title` line (its text checked in `split_title`), blank lines, then the
# header's opening fence. Every repetition consumes a newline, so the match stays linear.
_TITLE_FIRST = re.compile(r"\A(?:[ \t]*\r?\n)*(# [^\r\n]*\r?\n)(?:[ \t]*\r?\n)*(?=---)")
# A CommonMark closing sequence: trailing `#`s that are the whole text or follow a blank. `# #` is
# an empty heading; `# C#` is not.
_CLOSING = re.compile(r"(?:\A|[ \t])#+\Z")
_MISSING = "missing or malformed YAML frontmatter (expected leading '---' block)"
_MISSING_AFTER_TITLE = (
    "missing or malformed YAML frontmatter (expected a leading '---' block, or one '# Title' line "
    "and then the '---' block)"
)


class FrontmatterError(ValueError):
    """Raised when frontmatter is missing or malformed."""


def split_title(text: str) -> tuple[str, str]:
    """``(title, rest)`` when ``text`` opens with one ``# Title`` line followed by a line starting
    ``---``; ``("", text)`` otherwise. The header itself is checked by the caller.

    ``title`` is the title line as written, with its own line ending; ``rest`` starts at the
    ``---`` line. Blank lines before and after the title are dropped. The title needs text once a
    closing sequence of ``#``s is removed, so ``# #`` and ``# ###`` are empty and ``# C#`` is not.
    Anything else before the header (a second H1, an H2, ``#Title`` without the space, prose, a
    BOM) is not a title, so the text comes back whole and the strict header check refuses it.
    """
    head = _TITLE_FIRST.match(text)
    if head is None or not _CLOSING.sub("", head.group(1)[2:].strip()).strip():
        return "", text
    return head.group(1), text[head.end() :]


def parse(text: str, *, allow_title: bool = False) -> tuple[dict[str, Any], str]:
    """Split markdown text into (frontmatter_mapping, body).

    Raises FrontmatterError if the leading YAML frontmatter block is missing or is
    not a mapping. With ``allow_title`` (handoff artifacts only, ADR 0112) one ``# Title`` line
    may come before the block (:func:`split_title`); the body then starts with that line, so the
    title is not lost.
    """
    title = ""
    if allow_title:
        title, text = split_title(text)
    match = _FRONTMATTER.match(text)
    if match is None:
        raise FrontmatterError(_MISSING_AFTER_TITLE if allow_title else _MISSING)

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

    return data, title + match.group(2)
