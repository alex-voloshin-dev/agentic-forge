"""Build a GitHub pull-request review from a reviewer's findings (``af.py pr-review``).

A session used to hand-build each review as a ``gh api -X POST .../pulls/<n>/reviews`` call, and
four things went wrong with it: the review attached to whatever the head was when it posted, not the
commit that was reviewed; an inline comment on a line outside the diff was refused with a 422 and
took the whole review with it; a bare ``@name`` in a finding notified a real person; and the shape
of each comment varied. This module is the pure half: it validates the findings, reads the PR's
unified diff for the lines GitHub accepts a comment on, places each finding inline or in the body,
neutralises every mention, caps the sizes, and maps the verdict to a review event. The ``gh`` reads
and the file write are ``af.py``'s; posting is the session's, from the printed command.

On one's own PR GitHub refuses REQUEST_CHANGES, so a ``changes`` verdict posts as a COMMENT, and the
merge gates hold a PR on unresolved review threads, not on a comment's body. There every finding
that would sit in the body only is also posted as a thread anchored on the diff (ADR 0110,
amendment), so the review still holds the merge until the threads are resolved.

Hook-reachable through ``af.py`` (ADR 0104), so Python 3.9 and the standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .handoff import BLOCKING_SEVERITIES, SEVERITIES, VERDICTS

__all__ = [
    "COMMIT_ID",
    "EVENTS",
    "MAX_FINDINGS",
    "MAX_COMMENT_CHARS",
    "MAX_BODY_CHARS",
    "MAX_DIFF_CHARS",
    "OMITTED_REASON",
    "NO_ANCHOR_WARNING",
    "HEAD_QUERY",
    "Finding",
    "Review",
    "PrHead",
    "Placement",
    "HoldThread",
    "BuiltReview",
    "parse_findings",
    "parse_location",
    "commentable_lines",
    "neutralise_mentions",
    "review_event",
    "holds_by_thread",
    "head_query_argv",
    "diff_argv",
    "post_argv",
    "parse_head",
    "reviewable_problem",
    "build_review",
]

# A full commit id as GitHub gives it (SHA-1 or SHA-256), lowercase: the review is pinned to it.
COMMIT_ID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")

# What `--event` may ask for. The verdict decides the rest (see review_event).
EVENTS = ("request-changes", "comment", "approve")

# Bounds. GitHub refuses a comment or a review body over 65,536 characters; a review this tool
# builds stays well under, so a reader is not handed a wall, and the payload stays small.
MAX_FINDINGS = 200
MAX_COMMENT_CHARS = 8000
MAX_BODY_CHARS = 60000
MAX_DIFF_CHARS = 16 * 1024 * 1024
_MAX_LOCATION_CHARS = 500
# The placement reason of a finding the body had no room left for: it is not in the body, and the
# session has to say so. Unless a hold thread carries it (see build_review), it is nowhere.
OMITTED_REASON = "omitted: body cap"
# What a hold thread opens with: where the finding really is, and that the line it is attached to
# is a stand-in. Explicit, because the PR watcher's fixer is handed a thread as "Address this review
# comment on <anchor>:" and would otherwise take the anchor for the place to edit.
_HOLD_NOTE = (
    "This thread sits here only to hold the merge; the line it is attached to is not the finding's."
)
_OUTSIDE_PREFIX = "Finding at {location}. " + _HOLD_NOTE
_NO_LOCATION_PREFIX = "Finding without a file:line. " + _HOLD_NOTE
NO_ANCHOR_WARNING = (
    "nothing in the diff to anchor a thread on; this review will not hold a merge"
)

# One read: who is asking (GitHub refuses a review that approves or requests changes on one's own
# PR), and the PR's state, head and author. Read-only.
HEAD_QUERY = (
    "query($owner:String!,$name:String!,$number:Int!){viewer{login} "
    "repository(owner:$owner,name:$name){pullRequest(number:$number)"
    "{number state headRefOid author{login}}}}"
)

_ISSUE_KEYS = ("issue", "description")
_FIX_KEYS = ("suggestion", "fix")
_LOCATION = re.compile(r"(?P<path>.+?):L?(?P<start>\d+)(?:\s*[-–]\s*L?(?P<end>\d+))?(?::\d+)?")
_HUNK = re.compile(
    r"@@ -(?P<from>\d+)(?:,(?P<old>\d+))? \+(?P<new>\d+)(?:,(?P<count>\d+))? @@"
)

# Every `@` that could start a mention: one not right after an ASCII letter or digit (that is an
# email address, which GitHub does not link), and not already followed by the zero-width space. What
# follows it is not looked at: `@&#97;lice` renders as `@alice`.
_ZERO_WIDTH_SPACE = "\u200b"
_MENTION = re.compile(r"(?<![A-Za-z0-9])@(?!\u200b)")
# `@` written as a character reference, which GitHub renders as `@` before it looks for mentions.
_AT_REFERENCE = re.compile(r"&(?:#0*64|#x0*40|commat);?", re.IGNORECASE)
# A `<` that starts a line, after any blockquote or list markers: it can open an HTML block, and an
# unclosed `<!--`, `<pre` or `<script` would hide every finding after it.
_LINE_START_TAG = re.compile(r"^([ \t>*+\-0-9.)]*)<", re.MULTILINE)
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


@dataclass(frozen=True)
class Finding:
    """One finding, in the shape the review handoff and the reviewer roles emit."""

    severity: str
    location: str
    issue: str
    fix: str
    evidence: str = ""


@dataclass(frozen=True)
class Review:
    """What the findings file holds: a verdict (given, or derived from the severities), an optional
    summary for the body, and the findings."""

    verdict: str
    findings: list[Finding]
    summary: str = ""


@dataclass(frozen=True)
class PrHead:
    """What has to hold right before a review is built for a PR."""

    number: int
    state: str
    head_oid: str
    author: str
    viewer: str

    @property
    def own(self) -> bool:
        """The account posting is the PR's author, which GitHub refuses an approve or a request for
        changes from."""
        return bool(self.author) and self.author.casefold() == self.viewer.casefold()


@dataclass
class Placement:
    """Where a finding went, and why not inline when it did not."""

    location: str
    inline: bool
    reason: str = ""


@dataclass(frozen=True)
class HoldThread:
    """A finding the body carries that was also posted as a thread, so the review holds the merge:
    the finding's own location, and the diff line the thread is anchored on. ``side`` is ``RIGHT``
    for an added or context line (its new number), ``LEFT`` for a removed one (its old number)."""

    location: str
    path: str
    line: int
    side: str = "RIGHT"


@dataclass
class BuiltReview:
    """The payload, where each finding went, how many did not fit the body, the hold threads, and
    what the session must be told (each also stated in the body)."""

    payload: dict[str, Any]
    placements: list[Placement] = field(default_factory=list)
    omitted: int = 0  # findings that did not fit the body's cap
    threads: list[HoldThread] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# --- the findings ---------------------------------------------------------------------------------


def _text(entry: dict[str, Any], keys: tuple[str, ...], index: int) -> str:
    """The first of ``keys`` the finding has (they are synonyms, see patterns/handoff.md)."""
    for key in keys:
        if key in entry:
            value = entry[key]
            if not isinstance(value, str):
                raise ValueError(f"finding {index}: {key!r} must be a string")
            return value.strip()
    return ""


def _finding(entry: Any, index: int) -> Finding:
    if not isinstance(entry, dict):
        raise ValueError(f"finding {index} must be a JSON object")
    severity = entry.get("severity")
    if severity not in SEVERITIES:
        raise ValueError(f"finding {index}: 'severity' must be one of {', '.join(SEVERITIES)}")
    location = entry.get("location")
    if not isinstance(location, str) or not location.strip():
        raise ValueError(f"finding {index} needs a 'location' (file:line)")
    if len(location) > _MAX_LOCATION_CHARS:
        raise ValueError(f"finding {index}: 'location' is over {_MAX_LOCATION_CHARS} characters")
    issue = _text(entry, _ISSUE_KEYS, index)
    if not issue:
        raise ValueError(f"finding {index} needs an 'issue' (what is wrong)")
    fix = _text(entry, _FIX_KEYS, index)
    if not fix:
        raise ValueError(f"finding {index} needs a 'suggestion' (the concrete fix)")
    evidence = _text(entry, ("evidence",), index)
    return Finding(severity, location.strip(), issue, fix, evidence)


def parse_findings(data: Any) -> Review:
    """A :class:`Review` from a findings file: a JSON array of findings, or an object with
    ``findings`` (and optionally ``verdict`` and ``summary``), as a ``review.md`` header has them;
    its other keys are ignored.

    Each finding needs ``severity`` (the handoff vocabulary), ``location``, ``issue`` (or its
    synonym ``description``) and ``suggestion`` (or ``fix``); ``evidence`` is optional and other
    keys are ignored. Without a ``verdict`` it is derived: any blocker or major is ``changes``. A
    given ``approve`` over a blocker or major is refused, since the review rule says it cannot be
    one. Raises ``ValueError`` saying what is wrong."""
    verdict: Any = None
    summary: Any = ""
    if isinstance(data, dict):
        # Other keys of a review header are ignored; a missing `findings` is not, since a misspelt
        # key would otherwise read as no findings and post an approve.
        if "findings" not in data:
            raise ValueError("the findings object has no 'findings' key")
        verdict = data.get("verdict")
        summary = data.get("summary", "")
        entries = data["findings"]
    else:
        entries = data
    if not isinstance(entries, list):
        raise ValueError(
            "the findings must be a JSON array, or an object with 'findings' holding one"
        )
    if len(entries) > MAX_FINDINGS:
        raise ValueError(
            f"{len(entries)} findings is more than one review carries ({MAX_FINDINGS})"
        )
    if not isinstance(summary, str):
        raise ValueError("'summary' must be a string")
    findings = [_finding(entry, index) for index, entry in enumerate(entries, start=1)]
    blocking = any(f.severity in BLOCKING_SEVERITIES for f in findings)
    if verdict is None:
        verdict = "changes" if blocking else "approve"
    elif verdict not in VERDICTS:
        raise ValueError(f"'verdict' must be one of {', '.join(VERDICTS)}")
    elif verdict == "approve" and blocking:
        raise ValueError(
            "the verdict is approve, but a finding is a blocker or major: that is changes"
        )
    return Review(verdict=verdict, findings=findings, summary=summary.strip())


def parse_location(location: str) -> tuple[str, int, int] | None:
    """``(path, start, end)`` from ``path:line``, ``path:start-end``, ``path:L12`` or
    ``path:line:column``; None when there is no line to anchor on."""
    match = _LOCATION.fullmatch(location.strip())
    if not match:
        return None
    path = match.group("path").strip()
    while path.startswith("./"):
        path = path[2:]
    start = int(match.group("start"))
    end = int(match.group("end") or start)
    if not path or start < 1 or end < start:
        return None
    return path, start, end


# --- the diff -------------------------------------------------------------------------------------


def _unquote(name: str) -> str:
    """A path as git writes it: C-quoted (``"b/caf\\303\\251"``) when it holds unusual bytes."""
    if not (len(name) >= 2 and name.startswith('"') and name.endswith('"')):
        return name
    raw = bytearray()
    body = name[1:-1]
    simple = {"n": 10, "t": 9, '"': 34, "\\": 92, "a": 7, "b": 8, "f": 12, "r": 13, "v": 11}
    i = 0
    while i < len(body):
        char = body[i]
        if char == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in simple:
                raw.append(simple[nxt])
                i += 2
                continue
            octal = body[i + 1:i + 4]
            if len(octal) == 3 and all(c in "01234567" for c in octal):
                raw.append(int(octal, 8))
                i += 4
                continue
        raw.extend(char.encode("utf-8"))
        i += 1
    return raw.decode("utf-8", errors="replace")


def _header_path(line: str, prefix: str) -> str | None:
    """The file a ``---``/``+++`` line names, without git's ``a/``/``b/`` (``prefix``); None for
    ``/dev/null`` (the old side of an added file, the new side of a deleted one)."""
    name = line[4:]
    if name.endswith("\t"):  # git ends a name holding a space with a tab
        name = name[:-1]
    name = _unquote(name)
    if name == "/dev/null":
        return None
    return name[2:] if name.startswith(prefix) else name


def _new_path(line: str) -> str | None:
    """The file a ``+++`` line names, without git's ``b/``; None for a deletion."""
    return _header_path(line, "b/")


@dataclass
class _DiffMap:
    """What a review needs from a unified diff. ``right``: :func:`commentable_lines`. ``left``: the
    removed lines' old numbers, keyed by the name GitHub gives the file (the new one; the old one
    for a deletion). ``first_added``: the first added line in diff order. ``renamed``: old path to
    new path."""

    right: dict[str, set[int]] = field(default_factory=dict)
    left: dict[str, set[int]] = field(default_factory=dict)
    first_added: tuple[str, int] | None = None
    renamed: dict[str, str] = field(default_factory=dict)


def commentable_lines(diff: str) -> dict[str, set[int]]:
    """For each file a unified diff changes, the new-file line numbers GitHub accepts an inline
    comment on: the added and context lines of each hunk (the RIGHT side). A deleted file has
    none, and neither has a rename or a mode change without a hunk. A hunk is read by its line
    counts, so a removed line that reads ``--- x`` is content, not a header. Lines end at ``\n``
    only: a ``\r`` is part of a line, as it is to git and GitHub."""
    return _read_diff(diff).right


def _read_diff(diff: str) -> _DiffMap:
    """The :class:`_DiffMap` of ``diff``, read as :func:`commentable_lines` reads it. A rename is
    taken from ``rename from``/``rename to`` (a rename with no hunk has only those) and from a
    ``---``/``+++`` pair that names two paths."""
    found = _DiffMap()
    current: str | None = None  # the new path, which RIGHT lines are keyed by
    removed_key: str | None = None  # the name LEFT lines are keyed by
    old_name: str | None = None
    rename_from: str | None = None
    old_left = new_left = 0
    right = left = 0
    for line in diff.split("\n"):
        if old_left > 0 or new_left > 0:
            tag = line[:1]
            if tag == "+" and new_left > 0:
                if current is not None:
                    found.right[current].add(right)
                    if found.first_added is None:
                        found.first_added = (current, right)
                right += 1
                new_left -= 1
                continue
            if tag == "-" and old_left > 0:
                if removed_key is not None:
                    found.left.setdefault(removed_key, set()).add(left)
                left += 1
                old_left -= 1
                continue
            if (tag == " " or line == "") and old_left > 0 and new_left > 0:
                if current is not None:
                    found.right[current].add(right)
                right += 1
                left += 1
                old_left -= 1
                new_left -= 1
                continue
            if tag == "\\":
                continue
            old_left = new_left = 0  # a short hunk: read the line as a header
        if line.startswith("diff --git "):
            current = removed_key = old_name = rename_from = None
        elif line.startswith("rename from "):
            rename_from = _unquote(line[len("rename from "):])
        elif line.startswith("rename to ") and rename_from is not None:
            found.renamed[rename_from] = _unquote(line[len("rename to "):])
        elif line.startswith("--- "):
            old_name = _header_path(line, "a/")
        elif line.startswith("+++ "):
            current = _new_path(line)
            removed_key = current if current is not None else old_name
            if current is not None:
                found.right.setdefault(current, set())
                if old_name is not None and old_name != current:
                    found.renamed.setdefault(old_name, current)
            old_name = None  # used: a later `+++` without its own `---` must not inherit it
        elif line.startswith("@@ "):
            hunk = _HUNK.match(line)
            if hunk:  # a deleted file's hunk too: its counts say where the next header is
                old_left = int(hunk.group("old") or 1)
                new_left = int(hunk.group("count") or 1)
                right = int(hunk.group("new"))
                left = int(hunk.group("from"))
    return found


def _match(path: str, names: Any) -> str | None:
    """The one of ``names`` a finding's path names: the same; else the one that ends with it at a
    ``/`` (``app.py`` for ``src/app.py``), or that it ends with at a ``/`` (an absolute path, or one
    with git's ``a/`` or ``b/``). Two candidates is a guess, so None."""
    if path in names:
        return path
    found = [
        name for name in names
        if name.endswith("/" + path) or path.endswith("/" + name)
    ]
    return found[0] if len(found) == 1 else None


def _resolve_path(path: str, diff: _DiffMap) -> str | None:
    """The diff's (new) path for a finding's path, as :func:`_match` finds it among the files with
    a right side; else, when it names a renamed file's old path, that file's new path. An exact
    name wins over a suffix match on either side: a finding at ``a.py`` after ``a.py`` was renamed
    is that file, not another changed ``other/a.py``."""
    if path in diff.right:
        return path
    if path in diff.renamed and diff.renamed[path] in diff.right:
        return diff.renamed[path]
    found = _match(path, diff.right)
    if found is None:
        old = _match(path, diff.renamed)
        if old is not None and diff.renamed[old] in diff.right:
            found = diff.renamed[old]
    return found


# --- the text -------------------------------------------------------------------------------------


def neutralise_mentions(text: str) -> str:
    """``text`` as it is safe to post: every ``@`` that could start a mention followed by a
    zero-width space, ``@`` written as a character reference (``&#64;``, ``&#x40;``, ``&commat;``,
    any case) turned into that too, a ``<`` that starts a line escaped, and control characters
    other than newline and tab removed. An email address (``a@b.com``) is left alone; doing it
    twice changes nothing more.

    Nothing is exempt, code included. Telling code from prose the way GitHub does is CommonMark plus
    GFM plus raw HTML (a list item or a blockquote cuts a code span, a container ends a fence, an
    autolink or a tag beats a backtick, a table cell splits on ``|``), and every mistake there
    notifies a real person. A zero-width space in a code sample is the mistake that costs nothing
    but a character."""
    text = _CONTROL.sub("", text.replace("\r\n", "\n"))
    text = _AT_REFERENCE.sub("@", text)
    text = _MENTION.sub("@" + _ZERO_WIDTH_SPACE, text)
    return _LINE_START_TAG.sub(r"\1\\<", text)


def _capped(text: str, cap: int) -> str:
    """``text`` neutralised and within ``cap`` characters. It is cut before it is neutralised, so a
    cut cannot split a mention from its zero-width space; one that grew past the cap (a character
    per mention and per escaped ``<``) is cut shorter and done again."""
    limit = cap
    marker = "\n\n_(cut: over the size limit)_"
    while True:
        raw = text if len(text) <= limit else text[: max(limit - len(marker), 0)] + marker
        out = neutralise_mentions(raw)
        if len(out) <= cap:
            return out
        limit -= len(out) - cap


def _location_code(location: str) -> str:
    """A location as a code span: no backtick or line break can end it early."""
    clean = " ".join(_CONTROL.sub(" ", location).replace("`", "'").split())
    return f"`{clean}`"


def _comment_text(finding: Finding) -> str:
    """A finding as Markdown. Each field starts on a line of its own: a fence in it opens a block
    there, not an inline span that a blank line in the code would break open."""
    parts = [
        f"**{finding.severity}** · {_location_code(finding.location)}",
        finding.issue,
        "**Fix:**\n" + finding.fix,
    ]
    if finding.evidence:
        parts.append("**Evidence:**\n" + finding.evidence)
    return "\n\n".join(parts)


# --- the event ------------------------------------------------------------------------------------

_APPROVE_IS_A_COMMENT = (
    "an approve verdict is posted as a COMMENT: an APPROVE from this account counts toward the "
    "approvals branch protection requires and can open the merge gate on a model's judgement, so "
    "it is sent only with --event approve, when the user asked for one"
)


def review_event(verdict: str, requested: str, *, own_pr: bool) -> tuple[str, str]:
    """The GitHub review event for a verdict and ``--event``, and why.

    ``request-changes`` (the default) sends REQUEST_CHANGES for a ``changes`` verdict and COMMENT
    for an ``approve``. ``comment`` sends COMMENT for either. ``approve`` sends APPROVE, and only
    for an ``approve`` verdict. GitHub refuses REQUEST_CHANGES and APPROVE on one's own pull request
    (HTTP 422), so there it is COMMENT, and the reason says so."""
    if requested not in EVENTS:
        raise ValueError(f"--event must be one of {', '.join(EVENTS)}")
    if verdict not in VERDICTS:
        raise ValueError(f"unknown verdict {verdict!r}")
    if requested == "approve" and verdict != "approve":
        raise ValueError(
            "--event approve on a changes verdict: a review with changes cannot approve"
        )
    if requested == "comment":
        return "COMMENT", "--event comment"
    if verdict == "approve" and requested != "approve":
        return "COMMENT", _APPROVE_IS_A_COMMENT
    wanted = "APPROVE" if verdict == "approve" else "REQUEST_CHANGES"
    if own_pr:
        return "COMMENT", (
            f"GitHub refuses {wanted} on your own pull request, so the {verdict} verdict is posted "
            "as a COMMENT; the body states it"
        )
    if wanted == "APPROVE":
        return wanted, (
            "--event approve: this counts toward the approvals branch protection requires"
        )
    return wanted, "a changes verdict requests changes"


def holds_by_thread(verdict: str, requested: str, *, own_pr: bool) -> bool:
    """Whether every finding must sit on a review thread so the review holds the merge: a
    ``changes`` verdict that :func:`review_event` downgraded to COMMENT because the PR is one's own.

    The merge gates (the watcher's and the merge-preflight hook's) hold a PR on unresolved threads,
    not on a COMMENT's body, and in a fleet that pushes as one login every PR is one's own. Not for
    ``--event comment``: that is the caller choosing a review that does not request changes, and on
    another's PR REQUEST_CHANGES was there to choose. Not for a body as the marker either: a body
    is editable text, which a gate must not trust."""
    return verdict == "changes" and requested == "request-changes" and own_pr


# --- gh -------------------------------------------------------------------------------------------


def head_query_argv(owner: str, name: str, number: int) -> list[str]:
    """argv reading :data:`HEAD_QUERY` through ``gh api graphql`` (read-only). Owner and name go
    as strings (``-f``): ``-F`` would send a repository named ``2048`` as a number and ``null`` as
    null, and GitHub would refuse the query; only the number is typed."""
    return [
        "gh", "api", "graphql", "-f", f"owner={owner}", "-f", f"name={name}",
        "-F", f"number={number}", "-f", f"query={HEAD_QUERY}",
    ]


def diff_argv(slug: str, number: int) -> list[str]:
    """argv reading the PR's unified diff, the one GitHub places review comments on (read-only)."""
    return ["gh", "pr", "diff", str(number), "-R", slug, "--color", "never"]


def post_argv(slug: str, number: int, payload_file: str) -> list[str]:
    """argv posting a review payload file. The payload holds the commit it is pinned to."""
    return ["gh", "api", "-X", "POST", f"repos/{slug}/pulls/{number}/reviews",
            "--input", payload_file]


def parse_head(data: Any) -> PrHead:
    """:class:`PrHead` from the ``gh api graphql`` answer to :data:`HEAD_QUERY`. Not tolerant: an
    answer that does not say what the PR's head and state are raises ``ValueError``."""
    root = data.get("data") if isinstance(data, dict) else None
    if not isinstance(root, dict):
        raise ValueError("the answer from GitHub holds no data")
    repository = root.get("repository")
    pr = repository.get("pullRequest") if isinstance(repository, dict) else None
    if not isinstance(pr, dict):
        raise ValueError("GitHub has no such pull request in this repository")
    state, oid, number = pr.get("state"), pr.get("headRefOid"), pr.get("number")
    if not isinstance(state, str) or not isinstance(oid, str) or not isinstance(number, int):
        raise ValueError("the answer does not give the pull request's number, state and head")
    return PrHead(number=number, state=state.upper(), head_oid=oid.lower(),
                  author=_login(pr.get("author")), viewer=_login(root.get("viewer")))


def _login(actor: Any) -> str:
    login = actor.get("login") if isinstance(actor, dict) else None
    return login if isinstance(login, str) else ""


def reviewable_problem(head: PrHead, reviewed: str) -> str | None:
    """Why a review of ``reviewed`` must not be posted on this PR now, or None."""
    if head.state != "OPEN":
        return f"pull request #{head.number} is {head.state}: there is nothing to review"
    if head.head_oid != reviewed:
        return (
            f"pull request #{head.number}'s head is now {head.head_oid}, not the reviewed "
            f"{reviewed}: a push came in after the review. Review the new head (at least "
            f"{reviewed[:12]}..{head.head_oid[:12]}), then build again"
        )
    return None


# --- the review -----------------------------------------------------------------------------------


def _placement(finding: Finding, diff: _DiffMap) -> tuple[Placement, dict[str, Any]]:
    parsed = parse_location(finding.location)
    if parsed is None:
        return Placement(finding.location, False, "no file:line in the location"), {}
    path, start, end = parsed
    resolved = _resolve_path(path, diff)
    if resolved is None:
        return Placement(finding.location, False, "the file is not in the diff"), {}
    lines = diff.right[resolved]
    if not all(n in lines for n in range(start, end + 1)):
        return Placement(
            finding.location, False, "the line is not an added or context line of the diff"
        ), {}
    comment: dict[str, Any] = {"path": resolved, "line": end, "side": "RIGHT"}
    if end > start:
        comment.update({"start_line": start, "start_side": "RIGHT"})
    comment["body"] = _capped(_comment_text(finding), MAX_COMMENT_CHARS)
    return Placement(finding.location, True), comment


_Anchor = tuple[str, int, str]  # path, line, side (3.9 subscripts `tuple` at run time)


def _fallback_anchor(diff: _DiffMap) -> _Anchor | None:
    """The diff's first added line; with none, its first context line; with neither (a diff that
    only deletes files), its first removed line, on the LEFT side by its old number, where GitHub
    takes a comment too. With none of them (a rename or a binary change only), None: there is
    nothing a line comment can sit on."""
    if diff.first_added is not None:
        return diff.first_added[0], diff.first_added[1], "RIGHT"
    for side, files in (("RIGHT", diff.right), ("LEFT", diff.left)):
        for path, lines in files.items():
            if lines:
                return path, min(lines), side
    return None


def _hold_anchor(finding: Finding, diff: _DiffMap, fallback: _Anchor) -> tuple[_Anchor, str]:
    """Where a body finding's hold thread goes, and the line it opens with. In its own file when
    the diff has lines of it: the nearest added or context line to its range (the lower on a tie),
    else, for a file with no right side (a deletion), the nearest removed line on the LEFT.
    Otherwise the fallback anchor."""
    parsed = parse_location(finding.location)
    if parsed is None:
        return fallback, _NO_LOCATION_PREFIX
    prefix = _OUTSIDE_PREFIX.format(location=_location_code(finding.location))
    path, start, end = parsed

    def distance(n: int) -> tuple[int, int]:
        return (start - n if n < start else n - end if n > end else 0), n

    resolved = _resolve_path(path, diff)
    if resolved is not None and diff.right[resolved]:
        return (resolved, min(diff.right[resolved], key=distance), "RIGHT"), prefix
    removed = resolved if resolved is not None and resolved in diff.left else None
    if removed is None:
        removed = _match(path, diff.left)
    if removed is not None:
        return (removed, min(diff.left[removed], key=distance), "LEFT"), prefix
    return fallback, prefix


def _counts(findings: list[Finding]) -> str:
    counted = [f"{sum(f.severity == s for f in findings)} {s}" for s in SEVERITIES]
    return ", ".join(c for c in counted if not c.startswith("0 ")) or "no findings"


def build_review(
    review: Review, diff: str, *, head: str, event: str, event_reason: str, hold: bool = False
) -> BuiltReview:
    """The ``POST /repos/{owner}/{repo}/pulls/{n}/reviews`` payload for ``review`` on ``head``.

    A finding whose ``file:line`` (or ``file:start-end``) is on the RIGHT side of ``diff`` becomes
    an inline comment; any other goes into the body, saying why, since GitHub refuses the whole
    review over one comment outside the diff. Every text is neutralised and capped; the body holds
    the verdict, the counts and the commit it was reviewed at, and stops adding findings at its
    cap, saying how many it left out.

    With ``hold`` (pass :func:`holds_by_thread`) and a ``changes`` verdict, each finding that goes
    into the body is also posted as a thread, since the merge gates hold a PR on an unresolved
    thread and not on a COMMENT's body. It is anchored as :func:`_hold_anchor` says (its own file
    when it can be, else :func:`_fallback_anchor`), and opens with its real location and that the
    line it sits on is not the finding's. A finding the body cap leaves out still gets its thread.
    With no line anywhere a comment can sit on, or no finding at all, nothing can hold the merge:
    the body and :attr:`BuiltReview.warnings` say so."""
    if not COMMIT_ID.fullmatch(head):
        raise ValueError("the head to pin the review to is not a full commit id")
    mapped = _read_diff(diff)
    comments: list[dict[str, Any]] = []
    placements: list[Placement] = []
    in_body: list[tuple[Finding, Placement]] = []
    for finding in review.findings:
        placed, comment = _placement(finding, mapped)
        placements.append(placed)
        if placed.inline:
            comments.append(comment)
        else:
            in_body.append((finding, placed))
    inline = len(comments)

    threads: list[HoldThread] = []
    warnings: list[str] = []
    if hold and review.verdict == "changes":
        fallback = _fallback_anchor(mapped)
        if not review.findings:
            warnings.append(
                "a changes verdict with no findings: there is nothing to post as a thread; this "
                "review will not hold a merge"
            )
        elif in_body and fallback is None:
            warnings.append(NO_ANCHOR_WARNING)
        elif fallback is not None:
            for finding, placed in in_body:
                (path, line, side), prefix = _hold_anchor(finding, mapped, fallback)
                text = prefix + "\n\n" + _comment_text(finding) + f"\n\n_({placed.reason}.)_"
                comments.append({
                    "path": path, "line": line, "side": side,
                    "body": _capped(text, MAX_COMMENT_CHARS),
                })
                threads.append(HoldThread(finding.location, path, line, side))

    head_text = [
        f"**Review verdict: {review.verdict}** at `{head[:12]}` ({_counts(review.findings)}; "
        f"{inline} inline, {len(in_body)} below)."
    ]
    if event == "COMMENT" and event_reason != "--event comment":
        head_text.append(f"_Posted as a comment: {event_reason}._")
    if threads:
        head_text.append(
            f"_Each of the {len(threads)} finding(s) below is also posted as a review thread, "
            "anchored on the diff and opening with its real location, so this review holds the "
            "merge until those threads are resolved._"
        )
    head_text.extend(f"_**Warning:** {warning}._" for warning in warnings)
    if review.summary:
        head_text.append(_capped(review.summary, MAX_COMMENT_CHARS))
    body = "\n\n".join(head_text)
    omitted = 0
    for index, (finding, placed) in enumerate(in_body):
        where = placed.reason
        if threads:
            thread = threads[index]
            where += "; also posted as a thread on " + _location_code(
                f"{thread.path}:{thread.line}"
            )
            if thread.side == "LEFT":
                where += " (a removed line)"
        entry = _capped(_comment_text(finding) + f"\n\n_({where}.)_", MAX_COMMENT_CHARS)
        addition = "\n\n---\n\n" + entry
        if len(body) + len(addition) > MAX_BODY_CHARS - 200:
            omitted = len(in_body) - index
            for _, left_out in in_body[index:]:
                left_out.reason = OMITTED_REASON
            body += (
                f"\n\n---\n\n_{omitted} more finding(s) are not shown: the review body is capped "
                f"at {MAX_BODY_CHARS} characters"
                + ("; each is still posted as a review thread._" if threads else "._")
            )
            break
        body += addition
    payload: dict[str, Any] = {
        "commit_id": head, "event": event, "body": body, "comments": comments,
    }
    return BuiltReview(
        payload=payload, placements=placements, omitted=omitted, threads=threads,
        warnings=warnings,
    )
