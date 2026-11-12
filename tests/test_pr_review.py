"""``agentic_forge.pr_review``: the pure half of ``af.py pr-review``."""

from __future__ import annotations

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

@@ -20,3 +21,3 @@ def f():
 a
--- removed line that looks like a header
+++ added line that looks like a header
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
    # context line 21 and its added line 22, which only looks like a header
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
        ("snake_@x", "snake_@x"),
        ("a lone @ sign", "a lone @ sign"),
        ("é@dave", f"é@{_ZW}dave"),  # GitHub's \W is ASCII: a non-ASCII letter does not protect
        ("use `@types/node` here", "use `@types/node` here"),
        ("``a ` @x``", "``a ` @x``"),
        ("\\`@x`", f"\\`@{_ZW}x`"),  # an escaped backtick opens no span
        ("`unclosed @x", f"`unclosed @{_ZW}x"),
        ("`a\n\n@x`", f"`a\n\n@{_ZW}x`"),  # a span ends at a blank line
        ("```py\n@fixture\n```\n@eve", f"```py\n@fixture\n```\n@{_ZW}eve"),
        ("~~~\n@fixture\n~~~", "~~~\n@fixture\n~~~"),
        ("``` `x`\n@y", f"``` `x`\n@{_ZW}y"),  # a backtick in the info: not a fence
        ("bell\x07 @z\r\n", f"bell @{_ZW}z\n"),
    ],
)
def test_neutralise_mentions(text: str, expected: str) -> None:
    assert pr_review.neutralise_mentions(text) == expected


def test_an_open_fence_is_closed_so_it_cannot_swallow_what_follows() -> None:
    assert pr_review.neutralise_mentions("```\n@x") == "```\n@x\n```"
    assert pr_review.neutralise_mentions("~~~~\n@x\n~~~") == "~~~~\n@x\n~~~\n~~~~"


def test_inside_an_html_block_code_is_not_code_so_everything_is_neutralised() -> None:
    text = "<div>\n```\n@x\n```\n`@y`\n</div>"
    out = pr_review.neutralise_mentions(text)
    assert "@x" not in out and "@y" not in out
    assert out.count(_ZW) == 2


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
    assert query[:3] == ["gh", "api", "graphql"] and "number=7" in query


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


def test_an_ambiguous_tail_is_not_guessed() -> None:
    diff = "+++ b/a/x.py\n@@ -1 +1 @@\n-p\n+q\n+++ b/b/x.py\n@@ -1 +1 @@\n-p\n+q\n"
    review = pr_review.parse_findings([_finding(location="x.py:1")])
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
    assert "`a'b @x c`" in built.payload["body"]


def test_a_comment_is_capped_and_its_mentions_still_neutralised() -> None:
    long_issue = "@zed " * 5000  # 25,000 characters, a mention every five
    built = _build([_finding(issue=long_issue)])
    body = built.payload["comments"][0]["body"]
    assert len(body) <= pr_review.MAX_COMMENT_CHARS
    assert body.endswith("_(cut: over the size limit)_")
    assert "@zed" not in body


def test_a_cut_cannot_open_a_code_span_the_neutraliser_had_closed() -> None:
    """Cut first, then neutralise: a span cut in half is no span, so its mention is neutralised."""
    issue = "x" * (pr_review.MAX_COMMENT_CHARS - 200) + " `@inside the span " + "y" * 400 + "`"
    body = _build([_finding(issue=issue)]).payload["comments"][0]["body"]
    assert "@inside" not in body and f"@{_ZW}inside" in body


def test_the_body_stops_at_its_cap_and_says_how_many_it_left_out() -> None:
    findings = [_finding(location=f"elsewhere.py:{n}", issue="i" * 6000) for n in range(1, 31)]
    built = _build(findings)
    body = built.payload["body"]
    assert len(body) <= pr_review.MAX_BODY_CHARS
    assert built.omitted > 0
    assert f"_{built.omitted} more finding(s) are not shown" in body


def test_build_refuses_a_head_that_is_not_a_commit_id() -> None:
    with pytest.raises(ValueError, match="full commit id"):
        _build([], head="abc123")
