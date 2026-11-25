"""``agentic_forge.pr_review``: the pure half of ``af.py pr-review``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agentic_forge import pr_review
from agentic_forge.pr_review import Finding, PrHead, Review

_HEAD = "b" * 40
_ZW = "\u200b"


def _finding(**fields: Any) -> dict[str, Any]:
    base = {"severity": "major", "location": "src/app.py:3", "issue": "Off by one.",
            "suggestion": "Use < instead of <=."}
    base.update(fields)
    return base


# --- the diff -------------------------------------------------------------------------------------

_DIFF = """\
diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,4 +1,5 @@
 import os
-x = 1
+x = 2
+y = 3
 z = 4

@@ -20,2 +21,2 @@ def f():
 a
--- removed line that looks like a header
+++ b/evil.py
diff --git a/old/name.py b/new/name.py
similarity index 90%
rename from old/name.py
rename to new/name.py
index 3333333..4444444 100644
--- a/old/name.py
+++ b/new/name.py
@@ -7 +7 @@
-before
+after
diff --git a/moved.py b/moved_too.py
similarity index 100%
rename from moved.py
rename to moved_too.py
diff --git a/gone.py b/gone.py
deleted file mode 100644
index 5555555..0000000
--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-++ b/evil.py
-last
diff --git a/new file.txt b/new file.txt
new file mode 100644
index 0000000..6666666
--- /dev/null
+++ b/new file.txt\t
@@ -0,0 +1,2 @@
+one
+two
\\ No newline at end of file
diff --git "a/caf\\303\\251.md" "b/caf\\303\\251.md"
index 7777777..8888888 100644
--- "a/caf\\303\\251.md"
+++ "b/caf\\303\\251.md"
@@ -1 +1 @@
-old
+new
diff --git a/bin.png b/bin.png
index 9999999..aaaaaaa 100644
Binary files a/bin.png and b/bin.png differ
"""


def test_commentable_lines_are_the_right_side_of_each_hunk() -> None:
    files = pr_review.commentable_lines(_DIFF)
    # added (2, 3), context (1, 4, the empty context line 5) in the first hunk; the second hunk's
    # context line 21 and its added line 22, whose raw text is `+++ b/evil.py`: content, by count
    assert files["src/app.py"] == {1, 2, 3, 4, 5, 21, 22}
    assert files["new/name.py"] == {7}  # a renamed file is keyed by its new name
    assert "old/name.py" not in files
    assert "moved_too.py" not in files  # a rename with no hunk has nothing to comment on
    assert "gone.py" not in files and "evil.py" not in files  # a deletion has no right side
    assert files["new file.txt"] == {1, 2}  # the tab git adds after a name with a space is not it
    assert files["café.md"] == {1}  # a C-quoted name is decoded
    assert "bin.png" not in files


def test_a_deleted_line_is_not_commentable() -> None:
    files = pr_review.commentable_lines(_DIFF)
    # x = 1 was old line 2; new line 2 is the added x = 2, so 2 is commentable, but nothing past the
    # hunks is (lines 6 to 20 sit between the two hunks)
    assert not files["src/app.py"] & set(range(6, 21))


def test_a_diff_with_no_prefix_and_no_counts() -> None:
    diff = "--- x.py\n+++ x.py\n@@ -3 +3 @@\n-a\n+b\n"
    assert pr_review.commentable_lines(diff) == {"x.py": {3}}


def test_a_carriage_return_inside_a_line_is_content() -> None:
    """Git and GitHub end a line at \\n only; `+a\\r b` is one added line, so `+c` is line 2."""
    diff = "+++ b/a.py\n@@ -0,0 +1,2 @@\n+a\r b\n+c\n"
    assert pr_review.commentable_lines(diff) == {"a.py": {1, 2}}


def test_a_short_hunk_does_not_swallow_the_next_header() -> None:
    diff = (
        "+++ b/a.py\n@@ -1,5 +1,5 @@\n-x\n+y\n"
        "diff --git a/b.py b/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-p\n+q\n"
    )
    assert pr_review.commentable_lines(diff) == {"a.py": {1}, "b.py": {1}}


@pytest.mark.parametrize(
    ("location", "parsed"),
    [
        ("src/app.py:3", ("src/app.py", 3, 3)),
        ("./src/app.py:3", ("src/app.py", 3, 3)),
        ("src/app.py:2-4", ("src/app.py", 2, 4)),
        ("src/app.py:L2-L4", ("src/app.py", 2, 4)),
        ("src/app.py:3:17", ("src/app.py", 3, 3)),
        ("C:/odd path/x.py:9", ("C:/odd path/x.py", 9, 9)),
        ("src/app.py", None),
        ("src/app.py:0", None),
        ("src/app.py:5-2", None),
        ("the auth layer", None),
    ],
)
def test_parse_location(location: str, parsed: tuple[str, int, int] | None) -> None:
    assert pr_review.parse_location(location) == parsed


# --- mentions -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ask @alice", f"ask @{_ZW}alice"),
        ("@bob first", f"@{_ZW}bob first"),
        ("cc @org/team-x.", f"cc @{_ZW}org/team-x."),
        ("(@carol)", f"(@{_ZW}carol)"),
        ("mail a@b.com", "mail a@b.com"),
        ("é@dave", f"é@{_ZW}dave"),  # GitHub's \\W is ASCII: a non-ASCII letter does not protect
        ("x _a_@alice", f"x _a_@{_ZW}alice"),  # `_` is emphasis, not part of a word, before `@`
        ("@&#97;lice", f"@{_ZW}&#97;lice"),  # what follows the `@` is not looked at
        ("a lone @ sign", f"a lone @{_ZW} sign"),
        ("bell\x07 @z\r\n", f"bell @{_ZW}z\n"),
        # code is not exempt
        ("use `@types/node` here", f"use `@{_ZW}types/node` here"),
        ("```py\n@fixture\n```", f"```py\n@{_ZW}fixture\n```"),
    ],
)
def test_neutralise_mentions(text: str, expected: str) -> None:
    assert pr_review.neutralise_mentions(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "a `x\n- @alice `y`",  # a list item after an unclosed backtick cuts the span
        "> ```\n@alice\n```",  # a blockquote's fence ends with the blockquote
        "<https://x.test/`>@alice`",  # an autolink beats the backtick
        "| `x | @alice` |\n| - | - |",  # a GFM table cell splits on |
        '<span title="`">@alice @org/team</span>',  # a raw tag beats the backtick
        "x _a_@alice",
        "&#64;alice", "&#064;alice", "&#x40;alice", "&#X40;alice", "&#x0040;alice",
        "&commat;alice", "&CoMmAt;alice", "&#64alice",
    ],
)
def test_the_bypass_shapes_are_all_neutralised(text: str) -> None:
    out = pr_review.neutralise_mentions(text)
    for login in ("alice", "org/team"):
        if login in out:
            assert f"@{_ZW}{login}" in out, out
            assert out.count(f"@{login}") == 0, out
    assert "&#" not in out and "&commat" not in out.lower()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("<!-- hide the rest", "\\<!-- hide the rest"),
        ("ok\n<script>x</script>", "ok\n\\<script>x</script>"),
        ("   <pre>", "   \\<pre>"),
        ("> <details>", "> \\<details>"),
        ("- 1. <div>", "- 1. \\<div>"),
        ("a <b>inline</b>", "a <b>inline</b>"),  # not at a line start: no block opens
    ],
)
def test_a_tag_at_a_line_start_is_escaped(text: str, expected: str) -> None:
    assert pr_review.neutralise_mentions(text) == expected


def test_neutralising_twice_changes_nothing_more() -> None:
    text = "<!--\n@a &#64;b `@c`\n> <x>"
    once = pr_review.neutralise_mentions(text)
    assert pr_review.neutralise_mentions(once) == once


def test_the_source_holds_no_invisible_character() -> None:
    source = Path(pr_review.__file__).read_text(encoding="utf-8")
    assert "\u200b" not in source
    assert '"\\u200b"' in source


# --- the findings ---------------------------------------------------------------------------------


def test_findings_as_an_array_derive_the_verdict() -> None:
    review = pr_review.parse_findings([_finding(), _finding(severity="nit")])
    assert review.verdict == "changes"
    assert pr_review.parse_findings([_finding(severity="minor")]).verdict == "approve"
    assert pr_review.parse_findings([]).verdict == "approve"


def test_findings_as_a_review_header_with_synonyms() -> None:
    data = {
        "type": "review", "target": "PR 7", "iteration": 1, "verdict": "changes",
        "summary": " Tight. ",
        "findings": [{"severity": "minor", "location": "a.py:1", "description": "d",
                      "fix": "f", "evidence": "e", "aspect": "correctness"}],
    }
    review = pr_review.parse_findings(data)
    assert review == Review("changes", [Finding("minor", "a.py:1", "d", "f", "e")], "Tight.")


@pytest.mark.parametrize(
    ("data", "says"),
    [
        ("x", "must be a JSON array"),
        ({"finding": []}, "no 'findings' key"),
        ({"findings": {}}, "must be a JSON array"),
        ([1], "finding 1 must be a JSON object"),
        ([_finding(severity="critical")], "'severity' must be one of"),
        ([_finding(severity=None)], "'severity' must be one of"),
        ([_finding(location="")], "needs a 'location'"),
        ([_finding(location=3)], "needs a 'location'"),
        ([_finding(location="x" * 501)], "over 500"),
        ([{**_finding(), "issue": ""}], "needs an 'issue'"),
        ([{k: v for k, v in _finding().items() if k != "issue"}], "needs an 'issue'"),
        ([{k: v for k, v in _finding().items() if k != "suggestion"}], "needs a 'suggestion'"),
        ([_finding(issue=["a"])], "'issue' must be a string"),
        ({"findings": [], "verdict": "lgtm"}, "'verdict' must be one of"),
        ({"findings": [_finding()], "verdict": "approve"}, "that is changes"),
        ({"findings": [], "summary": 3}, "'summary' must be a string"),
        ([_finding()] * 201, "more than one review carries"),
    ],
)
def test_malformed_findings_are_refused(data: Any, says: str) -> None:
    with pytest.raises(ValueError, match=says):
        pr_review.parse_findings(data)


# --- the event ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("verdict", "requested", "own", "event"),
    [
        ("changes", "request-changes", False, "REQUEST_CHANGES"),
        ("changes", "comment", False, "COMMENT"),
        ("approve", "request-changes", False, "COMMENT"),
        ("approve", "comment", False, "COMMENT"),
        ("approve", "approve", False, "APPROVE"),
        ("changes", "request-changes", True, "COMMENT"),
        ("approve", "approve", True, "COMMENT"),
    ],
)
def test_review_event(verdict: str, requested: str, own: bool, event: str) -> None:
    got, reason = pr_review.review_event(verdict, requested, own_pr=own)
    assert got == event
    assert reason


def test_an_approve_says_why_it_is_a_comment() -> None:
    _, reason = pr_review.review_event("approve", "request-changes", own_pr=False)
    assert "branch protection" in reason and "--event approve" in reason
    _, own = pr_review.review_event("changes", "request-changes", own_pr=True)
    assert "your own pull request" in own


@pytest.mark.parametrize(
    ("verdict", "requested", "says"),
    [("changes", "approve", "cannot approve"), ("changes", "merge", "--event must be"),
     ("lgtm", "comment", "unknown verdict")],
)
def test_review_event_refuses(verdict: str, requested: str, says: str) -> None:
    with pytest.raises(ValueError, match=says):
        pr_review.review_event(verdict, requested, own_pr=False)


# --- gh -------------------------------------------------------------------------------------------


def _answer(**pr: Any) -> dict[str, Any]:
    node = {"number": 7, "state": "OPEN", "headRefOid": _HEAD, "author": {"login": "Ann"}}
    node.update(pr)
    return {"data": {"viewer": {"login": "ann"}, "repository": {"pullRequest": node}}}


def test_parse_head() -> None:
    head = pr_review.parse_head(_answer(headRefOid=_HEAD.upper(), state="open"))
    assert head == PrHead(7, "OPEN", _HEAD, "Ann", "ann")
    assert head.own  # logins compare case-insensitively
    assert not pr_review.parse_head(_answer(author=None)).own


@pytest.mark.parametrize(
    ("answer", "says"),
    [
        ([], "holds no data"),
        ({"errors": []}, "holds no data"),
        ({"data": {"repository": None}}, "no such pull request"),
        ({"data": {"repository": {"pullRequest": None}}}, "no such pull request"),
        (_answer(headRefOid=None), "number, state and head"),
    ],
)
def test_parse_head_is_not_tolerant(answer: Any, says: str) -> None:
    with pytest.raises(ValueError, match=says):
        pr_review.parse_head(answer)


def test_reviewable_problem() -> None:
    assert pr_review.reviewable_problem(pr_review.parse_head(_answer()), _HEAD) is None
    moved = pr_review.reviewable_problem(pr_review.parse_head(_answer(headRefOid="c" * 40)), _HEAD)
    assert moved and "a push came in" in moved and "c" * 40 in moved
    for state in ("MERGED", "CLOSED"):
        shut = pr_review.reviewable_problem(pr_review.parse_head(_answer(state=state)), _HEAD)
        assert shut and state in shut


def test_the_argv_shapes() -> None:
    assert pr_review.post_argv("o/n", 7, "/tmp/p.json") == [
        "gh", "api", "-X", "POST", "repos/o/n/pulls/7/reviews", "--input", "/tmp/p.json"
    ]
    assert pr_review.diff_argv("o/n", 7)[:5] == ["gh", "pr", "diff", "7", "-R"]
    query = pr_review.head_query_argv("o", "n", 7)
    assert query[:3] == ["gh", "api", "graphql"]


@pytest.mark.parametrize("name", ["2048", "null", "true"])
def test_owner_and_name_go_as_strings_and_only_the_number_is_typed(name: str) -> None:
    query = pr_review.head_query_argv("o", name, 7)
    assert query[query.index(f"name={name}") - 1] == "-f"
    assert query[query.index("owner=o") - 1] == "-f"
    assert query[query.index("number=7") - 1] == "-F"


# --- the review -----------------------------------------------------------------------------------


def _build(findings: list[dict[str, Any]], **kwargs: Any) -> pr_review.BuiltReview:
    review = pr_review.parse_findings(findings)
    options = {"head": _HEAD, "event": "REQUEST_CHANGES", "event_reason": "r"}
    options.update(kwargs)
    return pr_review.build_review(review, _DIFF, **options)


def test_findings_on_the_diff_go_inline_and_the_rest_to_the_body() -> None:
    built = _build([
        _finding(location="src/app.py:3", issue="ping @alice"),  # added line
        _finding(location="src/app.py:4"),  # context line
        _finding(location="app.py:21", severity="minor"),  # a unique tail of a diff path
        _finding(location="src/app.py:2-3", severity="nit"),  # a range inside one hunk
        _finding(location="src/app.py:10"),  # between the hunks
        _finding(location="src/app.py:4-21", severity="nit"),  # a range across the gap
        _finding(location="untouched.py:1", issue="see @bob"),
        _finding(location="gone.py:1"),  # deleted file
        _finding(location="the design"),
    ])
    payload = built.payload
    assert payload["commit_id"] == _HEAD
    assert payload["event"] == "REQUEST_CHANGES"
    assert [(c["path"], c["line"], c["side"]) for c in payload["comments"]] == [
        ("src/app.py", 3, "RIGHT"), ("src/app.py", 4, "RIGHT"), ("src/app.py", 21, "RIGHT"),
        ("src/app.py", 3, "RIGHT"),
    ]
    ranged = payload["comments"][3]
    assert ranged["start_line"] == 2 and ranged["start_side"] == "RIGHT"
    assert "start_line" not in payload["comments"][0]
    first = payload["comments"][0]["body"]
    assert first.startswith("**major** · `src/app.py:3`")
    assert "**Fix:**\nUse < instead of <=." in first
    assert f"@{_ZW}alice" in first
    assert [p.inline for p in built.placements] == [True] * 4 + [False] * 5
    reasons = [p.reason for p in built.placements if not p.inline]
    assert reasons == [
        "the line is not an added or context line of the diff",
        "the line is not an added or context line of the diff",
        "the file is not in the diff", "the file is not in the diff",
        "no file:line in the location",
    ]
    body = payload["body"]
    assert body.startswith(f"**Review verdict: changes** at `{_HEAD[:12]}`")
    assert "4 inline, 5 below" in body
    assert f"@{_ZW}bob" in body and "@bob" not in body
    assert "_(the file is not in the diff.)_" in body
    assert built.omitted == 0


@pytest.mark.parametrize(
    "location",
    ["src/app.py:3", "b/src/app.py:3", "a/src/app.py:3", "/home/u/repo/src/app.py:3", "app.py:3"],
)
def test_a_finding_path_is_matched_at_a_slash(location: str) -> None:
    built = _build([_finding(location=location)])
    assert [c["path"] for c in built.payload["comments"]] == ["src/app.py"]


@pytest.mark.parametrize("location", ["rc/app.py:3", "/home/u/repo/xsrc/app.py:3"])
def test_a_path_is_not_matched_inside_a_name(location: str) -> None:
    assert _build([_finding(location=location)]).payload["comments"] == []


def test_an_ambiguous_tail_is_not_guessed() -> None:
    diff = "+++ b/a/x.py\n@@ -1 +1 @@\n-p\n+q\n+++ b/b/x.py\n@@ -1 +1 @@\n-p\n+q\n"
    for location in ("x.py:1", "/abs/x.py:1"):
        review = pr_review.parse_findings([_finding(location=location)])
        built = pr_review.build_review(review, diff, head=_HEAD, event="COMMENT", event_reason="r")
        assert built.payload["comments"] == []


def test_the_body_says_why_an_approve_is_a_comment() -> None:
    reason = "an approve verdict is posted as a COMMENT"
    built = _build([], event="COMMENT", event_reason=reason)
    assert f"_Posted as a comment: {reason}._" in built.payload["body"]
    plain = _build([], event="COMMENT", event_reason="--event comment")
    assert "Posted as a comment" not in plain.payload["body"]


def test_the_summary_is_neutralised_too() -> None:
    review = pr_review.parse_findings({"summary": "thanks @erin", "findings": []})
    built = pr_review.build_review(review, _DIFF, head=_HEAD, event="COMMENT", event_reason="r")
    assert f"@{_ZW}erin" in built.payload["body"]


def test_a_location_cannot_break_out_of_its_code_span() -> None:
    built = _build([_finding(location="a`b @x\n\nc")])
    assert f"`a'b @{_ZW}x c`" in built.payload["body"]


def test_a_comment_is_capped_and_its_mentions_still_neutralised() -> None:
    long_issue = "@zed " * 5000  # 25,000 characters, a mention every five
    built = _build([_finding(issue=long_issue)])
    body = built.payload["comments"][0]["body"]
    assert len(body) <= pr_review.MAX_COMMENT_CHARS
    assert body.endswith("_(cut: over the size limit)_")
    assert "@zed" not in body


def test_the_body_stops_at_its_cap_and_says_how_many_it_left_out() -> None:
    findings = [_finding(location=f"elsewhere.py:{n}", issue="i" * 6000) for n in range(1, 31)]
    built = _build(findings)
    body = built.payload["body"]
    assert len(body) <= pr_review.MAX_BODY_CHARS
    assert built.omitted > 0
    assert f"_{built.omitted} more finding(s) are not shown" in body
    dropped = [p for p in built.placements if p.reason == pr_review.OMITTED_REASON]
    assert len(dropped) == built.omitted
    assert built.placements[-1].reason == "omitted: body cap"
    assert built.placements[0].reason == "the file is not in the diff"


def test_build_refuses_a_head_that_is_not_a_commit_id() -> None:
    with pytest.raises(ValueError, match="full commit id"):
        _build([], head="abc123")


# --- the hold threads: a changes verdict on one's own PR (ADR 0110, amendment) -------------------


@pytest.mark.parametrize(
    ("verdict", "requested", "own", "hold"),
    [
        ("changes", "request-changes", True, True),
        ("changes", "request-changes", False, False),  # REQUEST_CHANGES itself holds
        ("changes", "comment", True, False),  # the caller chose a review that does not hold
        ("changes", "comment", False, False),
        ("approve", "request-changes", True, False),
        ("approve", "approve", True, False),
    ],
)
def test_holds_by_thread(verdict: str, requested: str, own: bool, hold: bool) -> None:
    assert pr_review.holds_by_thread(verdict, requested, own_pr=own) is hold


_NOTE = (
    "This thread sits here only to hold the merge; the line it is attached to is not the finding's."
)


def _held(
    findings: list[dict[str, Any]], diff: str = _DIFF, **review: Any
) -> pr_review.BuiltReview:
    parsed = pr_review.parse_findings({**review, "findings": findings})
    _, reason = pr_review.review_event(parsed.verdict, "request-changes", own_pr=True)
    return pr_review.build_review(
        parsed, diff, head=_HEAD, event="COMMENT", event_reason=reason, hold=True
    )


def test_a_finding_outside_the_diff_gets_a_thread_on_the_first_added_line() -> None:
    built = _held([_finding(location="src/app.py:3"), _finding(location="b.py:10", issue="Bad.")])
    comments = built.payload["comments"]
    assert [(c["path"], c["line"], c["side"]) for c in comments] == [
        ("src/app.py", 3, "RIGHT"), ("src/app.py", 2, "RIGHT"),  # line 2: the first `+` line
    ]
    thread = comments[1]["body"]
    assert thread.startswith(f"Finding at `b.py:10`. {_NOTE}\n\n**major** · `b.py:10`")
    assert "Bad." in thread and "_(the file is not in the diff.)_" in thread
    assert built.threads == [pr_review.HoldThread("b.py:10", "src/app.py", 2, "RIGHT")]
    assert built.warnings == []
    # the body still lists it, says where its thread is, and that the threads hold the merge
    body = built.payload["body"]
    assert "1 inline, 1 below" in body
    assert "also posted as a review thread" in body and "holds the merge" in body
    assert "_(the file is not in the diff; also posted as a thread on `src/app.py:2`.)_" in body
    assert [p.inline for p in built.placements] == [True, False]


@pytest.mark.parametrize(
    ("location", "line"),
    [
        ("src/app.py:10", 5),  # 5 is 5 away, 21 is 11
        ("src/app.py:15", 21),
        ("app.py:8-19", 21),  # a range: 21 is 2 past its end, 5 is 3 before its start
        ("src/app.py:13", 5),  # a tie goes to the lower line
        ("src/app.py:4-21", 4),  # a range across the gap that holds lines of the diff
    ],
)
def test_a_finding_on_a_line_outside_the_diff_gets_the_nearest_line_of_its_file(
    location: str, line: int
) -> None:
    built = _held([_finding(location=location)])
    [comment] = built.payload["comments"]
    assert (comment["path"], comment["line"]) == ("src/app.py", line)
    assert comment["body"].startswith(f"Finding at `{location}`. {_NOTE}")


@pytest.mark.parametrize("location", ["moved_too.py:3", "moved.py:3", "bin.png:1"])
def test_a_file_with_no_line_in_the_diff_falls_back_to_the_first_added_line(location: str) -> None:
    [comment] = _held([_finding(location=location)]).payload["comments"]
    assert (comment["path"], comment["line"], comment["side"]) == ("src/app.py", 2, "RIGHT")


@pytest.mark.parametrize(("location", "line"), [("gone.py:1", 1), ("gone.py:9", 2)])
def test_a_finding_in_a_deleted_file_sits_on_its_nearest_removed_line(
    location: str, line: int
) -> None:
    built = _held([_finding(location=location)])
    [comment] = built.payload["comments"]
    assert (comment["path"], comment["line"], comment["side"]) == ("gone.py", line, "LEFT")
    assert built.threads == [pr_review.HoldThread(location, "gone.py", line, "LEFT")]
    assert f"also posted as a thread on `gone.py:{line}` (a removed line)" in built.payload["body"]


def test_a_finding_without_a_location_gets_a_thread_on_the_first_added_line() -> None:
    built = _held([_finding(location="the design as a whole")])
    [comment] = built.payload["comments"]
    assert (comment["path"], comment["line"]) == ("src/app.py", 2)
    assert comment["body"].startswith(
        f"Finding without a file:line. {_NOTE}\n\n**major** · `the design as a whole`"
    )
    assert "_(no file:line in the location.)_" in comment["body"]


def test_an_approve_verdict_gets_no_hold_threads() -> None:
    built = _held([_finding(location="b.py:10", severity="minor")])
    assert built.payload["comments"] == []
    assert built.threads == [] and built.warnings == []
    assert "also posted as" not in built.payload["body"]


def test_a_review_that_requests_changes_is_unchanged() -> None:
    findings = [_finding(location="src/app.py:3"), _finding(location="b.py:10"),
                _finding(location="the design")]
    plain = _build(findings)
    assert plain == _build(findings, hold=False)
    assert [c["line"] for c in plain.payload["comments"]] == [3]
    assert plain.threads == [] and plain.warnings == []
    assert "also posted as" not in plain.payload["body"]


def test_a_diff_with_nothing_to_anchor_on_keeps_the_body_and_says_so() -> None:
    """A rename with no hunk or a binary change has no line a comment can sit on. A file-level
    comment (`subject_type: file`) is not used: the review endpoint's `comments[]` is not known to
    take it, and one refused comment takes the whole review with it."""
    diff = (
        "diff --git a/a.py b/b.py\nsimilarity index 100%\nrename from a.py\nrename to b.py\n"
        "diff --git a/bin.png b/bin.png\nindex 1..2 100644\n"
        "Binary files a/bin.png and b/bin.png differ\n"
    )
    for case in (diff, ""):
        built = _held([_finding(location="b.py:10"), _finding(location="the design")], diff=case)
        assert built.payload["comments"] == []
        assert built.warnings == [pr_review.NO_ANCHOR_WARNING]
        body = built.payload["body"]
        assert f"_**Warning:** {pr_review.NO_ANCHOR_WARNING}._" in body
        assert "`b.py:10`" in body and "`the design`" in body  # still in the body


def test_a_diff_that_only_removes_lines_anchors_on_its_first_context_line() -> None:
    diff = "--- a/x.py\n+++ b/x.py\n@@ -3,3 +3,2 @@\n keep\n-drop\n tail\n"
    [comment] = _held([_finding(location="y.py:1")], diff=diff).payload["comments"]
    assert (comment["path"], comment["line"], comment["side"]) == ("x.py", 3, "RIGHT")


def test_a_diff_that_only_deletes_files_anchors_on_the_first_removed_line() -> None:
    diff = (
        "diff --git a/a.py b/a.py\ndeleted file mode 100644\n--- a/a.py\n+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n-one\n-two\n"
        "diff --git a/b.py b/b.py\ndeleted file mode 100644\n--- a/b.py\n+++ /dev/null\n"
        "@@ -4 +0,0 @@\n-four\n"
    )
    built = _held([_finding(location="elsewhere.py:3"), _finding(location="the design"),
                   _finding(location="b.py:1")], diff=diff)
    assert [(c["path"], c["line"], c["side"]) for c in built.payload["comments"]] == [
        ("a.py", 1, "LEFT"), ("a.py", 1, "LEFT"), ("b.py", 4, "LEFT"),
    ]
    assert built.warnings == []


def test_the_removed_lines_are_numbered_on_the_old_side() -> None:
    mapped = pr_review._read_diff(_DIFF)
    # `-x = 1` was old line 2; the second hunk starts at old 20 with a context line, so the removed
    # `--- removed line that looks like a header` is old 21: content, by count
    assert mapped.left["src/app.py"] == {2, 21}
    assert mapped.left["gone.py"] == {1, 2}  # a deletion is keyed by its old name
    assert mapped.left["new/name.py"] == {7}  # a rename by its new one, as GitHub names it
    assert set(mapped.left) == {"src/app.py", "new/name.py", "gone.py", "café.md"}
    assert mapped.first_added == ("src/app.py", 2)


def test_a_rename_is_recorded_from_its_old_path_to_its_new_one() -> None:
    mapped = pr_review._read_diff(_DIFF)
    assert mapped.renamed == {"old/name.py": "new/name.py", "moved.py": "moved_too.py"}
    quoted = 'diff --git a/x b/y\nrename from "caf\\303\\251.py"\nrename to "t\\303\\251.py"\n'
    assert pr_review._read_diff(quoted).renamed == {"café.py": "té.py"}


@pytest.mark.parametrize("location", ["old/name.py:7", "a/old/name.py:7", "/repo/old/name.py:7"])
def test_a_finding_citing_a_renamed_files_old_path_is_placed_on_its_new_one(
    location: str
) -> None:
    built = _build([_finding(location=location)])
    assert [(c["path"], c["line"]) for c in built.payload["comments"]] == [("new/name.py", 7)]


def test_a_hold_thread_for_a_renamed_files_old_path_sits_in_the_new_file() -> None:
    [comment] = _held([_finding(location="old/name.py:30")]).payload["comments"]
    assert (comment["path"], comment["line"], comment["side"]) == ("new/name.py", 7, "RIGHT")


def test_a_changes_verdict_with_no_findings_says_it_cannot_hold() -> None:
    built = _held([], verdict="changes")
    assert built.payload["comments"] == []
    assert "will not hold a merge" in built.warnings[0]
    assert "will not hold a merge" in built.payload["body"]


def test_a_hold_thread_is_mention_safe() -> None:
    built = _held([_finding(location="a`b @x.py:9", issue="ask @carol &#64;dave")])
    [comment] = built.payload["comments"]
    text = comment["body"]
    # the backtick cannot end the code span early, and the `@` in the location is neutralised too
    assert text.startswith(f"Finding at `a'b @{_ZW}x.py:9`. {_NOTE}")
    assert f"@{_ZW}carol" in text and f"@{_ZW}dave" in text
    assert "@carol" not in text and "&#64;" not in text
    outside = _held([_finding(location="@eve/x.py:9")]).payload["comments"][0]["body"]
    assert outside.startswith(f"Finding at `@{_ZW}eve/x.py:9`. {_NOTE}")


def test_a_hold_thread_is_capped_and_keeps_its_real_location() -> None:
    built = _held([_finding(location="b.py:10", issue="@zed " * 5000)])
    [comment] = built.payload["comments"]
    assert len(comment["body"]) <= pr_review.MAX_COMMENT_CHARS
    assert comment["body"].startswith(f"Finding at `b.py:10`. {_NOTE}")
    assert comment["body"].endswith("_(cut: over the size limit)_")
    assert "@zed" not in comment["body"]


def test_a_finding_the_body_cap_leaves_out_still_gets_its_thread() -> None:
    findings = [_finding(location=f"elsewhere.py:{n}", issue="i" * 6000) for n in range(1, 31)]
    built = _held(findings)
    body = built.payload["body"]
    assert len(body) <= pr_review.MAX_BODY_CHARS
    assert built.omitted > 0
    assert f"_{built.omitted} more finding(s) are not shown" in body
    assert "each is still posted as a review thread._" in body
    assert len(built.payload["comments"]) == len(built.threads) == 30
    assert [t.location for t in built.threads] == [f"elsewhere.py:{n}" for n in range(1, 31)]
    assert built.placements[-1].reason == pr_review.OMITTED_REASON
    # the thread keeps the reason it was placed with, not the body's cap
    assert "_(the file is not in the diff.)_" in built.payload["comments"][-1]["body"]


def test_an_exact_rename_source_wins_over_a_suffix_match_on_another_file() -> None:
    """``a.py`` renamed to ``b.py`` while ``other/a.py`` is modified: a finding at ``a.py`` is the
    renamed file, not a suffix match on the other one."""
    diff = (
        "diff --git a/a.py b/b.py\nsimilarity index 90%\nrename from a.py\nrename to b.py\n"
        "--- a/a.py\n+++ b/b.py\n@@ -1,2 +1,2 @@\n keep\n-old\n+new\n"
        "diff --git a/other/a.py b/other/a.py\n--- a/other/a.py\n+++ b/other/a.py\n"
        "@@ -1 +1,2 @@\n line\n+added\n"
    )
    mapped = pr_review._read_diff(diff)
    assert pr_review._resolve_path("a.py", mapped) == "b.py"
    assert pr_review._resolve_path("other/a.py", mapped) == "other/a.py"
    assert pr_review._resolve_path("b.py", mapped) == "b.py"
