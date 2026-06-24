from __future__ import annotations

import json

from agentic_forge.observability import Digest, digest, parse_lines, render


def _line(**kw: object) -> str:
    return json.dumps(kw)


SAMPLE = [
    _line(tool="Bash", input="ls", session_id="s1"),
    _line(tool="Read", input="a.py", session_id="s1"),
    _line(tool="Bash", input="git status", session_id="s2"),
    "",  # blank skipped
    "{not json",  # malformed skipped
    "[1,2]",  # non-dict skipped
]


# --- parse_lines -----------------------------------------------------------------------


def test_parse_lines_skips_blank_malformed_and_nondict() -> None:
    recs = parse_lines(SAMPLE)
    assert len(recs) == 3
    assert all(isinstance(r, dict) for r in recs)


# --- digest ----------------------------------------------------------------------------


def test_digest_counts_tools_sessions_and_top() -> None:
    d = digest(SAMPLE)
    assert d.total == 3
    assert d.by_tool == {"Bash": 2, "Read": 1}  # descending by count
    assert d.sessions == 2
    assert d.top_tool == "Bash"


def test_digest_empty() -> None:
    d = digest([])
    assert d == Digest(total=0, by_tool={}, sessions=0, top_tool=None)


def test_digest_tie_break_is_alphabetical() -> None:
    lines = [_line(tool="Zed", input="x"), _line(tool="Ack", input="y")]
    d = digest(lines)
    assert list(d.by_tool) == ["Ack", "Zed"]  # 1 each -> alphabetical
    assert d.top_tool == "Ack"


def test_digest_record_without_tool_or_session() -> None:
    d = digest([_line(input="x")])  # no tool, no session_id
    assert d.total == 1 and d.by_tool == {"unknown": 1} and d.sessions == 0


# --- render ----------------------------------------------------------------------------


def test_render_empty() -> None:
    assert "no tool-use records" in render(digest([]))


def test_render_summary() -> None:
    out = render(digest(SAMPLE))
    assert "3 tool uses across 2 session(s)" in out
    assert "Bash: 2" in out and "Read: 1" in out
