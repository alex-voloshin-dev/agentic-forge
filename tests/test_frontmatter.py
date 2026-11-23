from __future__ import annotations

import pytest

from agentic_forge.frontmatter import FrontmatterError, parse, split_title


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


# --- the title-first form, opt-in for handoff artifacts (ADR 0112) -------------------------------

_HEADER = "---\ntype: prd\n---\n"


@pytest.mark.parametrize(
    ("text", "body"),
    [
        ("# Export\n" + _HEADER + "Body\n", "# Export\nBody\n"),
        ("\n\n# Export\n\n\n" + _HEADER + "\nBody\n", "# Export\n\nBody\n"),
        (" \t\n# Export\n \n" + _HEADER, "# Export\n"),
        ("# Export: the *real* title #\n" + _HEADER, "# Export: the *real* title #\n"),
        ("# Title #\n" + _HEADER, "# Title #\n"),  # a closing sequence, kept as written
        ("# C#\n" + _HEADER, "# C#\n"),  # no blank before the `#`: text, not a closing sequence
        ("# C# ##\n" + _HEADER, "# C# ##\n"),
    ],
)
def test_a_title_may_come_before_the_header_when_allowed(text: str, body: str) -> None:
    fm, got = parse(text, allow_title=True)
    assert fm == {"type": "prd"}
    assert got == body  # the title stays: the body starts with it


@pytest.mark.parametrize(
    "text",
    [
        "# Export\n",  # a title and no header
        "# Export\nBody\n",
        "# Export\n\nBody\n" + _HEADER,  # text between the title and the header
        "# Export\n# Again\n" + _HEADER,  # two H1 lines
        "# Export\n\n# Again\n" + _HEADER,
        "## Export\n" + _HEADER,  # an H2
        "#Export\n" + _HEADER,  # no space after the hash
        "# \n" + _HEADER,  # an empty title
        "#   \t\n" + _HEADER,
        "# #\n" + _HEADER,  # only a closing sequence: an empty heading in CommonMark
        "# ###\n" + _HEADER,
        "# ## \n" + _HEADER,
        "intro\n# Export\n" + _HEADER,  # prose before the title
        "  # Export\n" + _HEADER,  # an indented title
        "\n" + _HEADER,  # blank lines alone are not a title
        "# Export\n---\ntype: prd\n",  # an unclosed header
    ],
)
def test_anything_else_before_the_header_is_refused(text: str) -> None:
    with pytest.raises(FrontmatterError, match="'# Title' line"):
        parse(text, allow_title=True)


def test_the_default_stays_strict() -> None:
    with pytest.raises(FrontmatterError, match=r"expected leading '---' block\)$"):
        parse("# Export\n" + _HEADER)


def test_crlf_is_read_as_today_with_or_without_a_title() -> None:
    assert parse("---\r\ntype: prd\r\n---\r\nBody\r\n") == ({"type": "prd"}, "Body\r\n")
    fm, body = parse("# Export\r\n\r\n---\r\ntype: prd\r\n---\r\nBody\r\n", allow_title=True)
    assert (fm, body) == ({"type": "prd"}, "# Export\r\nBody\r\n")


def test_a_bom_is_refused_as_today_with_or_without_a_title() -> None:
    with pytest.raises(FrontmatterError):
        parse("\ufeff" + _HEADER)
    with pytest.raises(FrontmatterError):
        parse("\ufeff" + _HEADER, allow_title=True)
    with pytest.raises(FrontmatterError):
        parse("\ufeff# Export\n" + _HEADER, allow_title=True)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("# Export\n" + _HEADER, ("# Export\n", _HEADER)),
        ("\n# Export\n\n" + _HEADER, ("# Export\n", _HEADER)),
        (_HEADER, ("", _HEADER)),
        ("## Export\n" + _HEADER, ("", "## Export\n" + _HEADER)),
        ("# Export\nBody\n", ("", "# Export\nBody\n")),
    ],
)
def test_split_title(text: str, expected: tuple[str, str]) -> None:
    assert split_title(text) == expected


def test_long_inputs_are_not_a_title() -> None:
    # Shapes that would cost a backtracking pattern quadratic time; no timing assertion (CI noise).
    text = " \n" * 200_000 + "# x " + " " * 200_000 + "\n"  # no header after the title
    assert split_title(text) == ("", text)
    hashes = "# " + "#" * 200_000 + "\n" + _HEADER  # only a closing sequence
    assert split_title(hashes) == ("", hashes)
    mixed = "# " + "## " * 50_000 + "x\n" + _HEADER  # text at the end: a real title
    assert split_title(mixed)[1] == _HEADER
