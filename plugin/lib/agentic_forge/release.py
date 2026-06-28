"""Release assembly: derive a semver bump and a Keep-a-Changelog grouping from the commits
since the last tag (Stage 4 ``release`` skill core; see docs/architecture/quality-ops.md).

The pure logic — classify a commit, compute the next version, group entries, summarise — is
deterministic and fully tested. Reading the git history (last tag + commit list) is a thin seam
(:func:`commits_since`) so the core is unit-tested without a repo; the ``release`` skill wires the
seam to real ``git``. Conventional-commit prefixes drive both the bump and the changelog group;
uncategorised commits still count toward a patch bump but are kept out of the changelog as noise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "Change",
    "Summary",
    "GROUP_ORDER",
    "classify",
    "next_version",
    "changelog_groups",
    "summarize",
    "commits_since",
]

# Conventional-commit type -> Keep-a-Changelog group. Types absent here are "other" (no group).
_TYPE_GROUP: dict[str, str] = {
    "feat": "Added",
    "fix": "Fixed",
    "perf": "Changed",
    "refactor": "Changed",
    "deprecate": "Deprecated",
    "security": "Security",
    "revert": "Removed",
    "remove": "Removed",
}
# Keep-a-Changelog section order for stable rendering.
GROUP_ORDER: tuple[str, ...] = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")

_HEADER = re.compile(r"^(?P<type>[a-zA-Z]+)(?:\([^)]*\))?(?P<bang>!)?:\s*(?P<desc>.+?)\s*$")
_BREAKING = re.compile(r"^BREAKING[ -]CHANGE:", re.MULTILINE)


@dataclass(frozen=True)
class Change:
    """One classified commit: its type, whether it is breaking, its changelog group, and the
    human description (the header text after the ``type:`` prefix, or the whole first line)."""

    type: str  # conventional type (lower-cased) or "other"
    breaking: bool
    group: str | None  # Keep-a-Changelog group, or None when uncategorised
    description: str


@dataclass(frozen=True)
class Summary:
    """The proposed release: the next version, the bump level applied, the grouped changelog
    entries (Keep-a-Changelog order), and the breaking-change descriptions called out."""

    current: str
    version: str
    bump: str  # "major" | "minor" | "patch" | "none"
    groups: dict[str, list[str]] = field(default_factory=dict)
    breaking: list[str] = field(default_factory=list)


def classify(message: str) -> Change:
    """Classify a single commit message (its first line is the header; the body may flag
    ``BREAKING CHANGE``). A ``type!:`` prefix or a ``BREAKING CHANGE`` trailer marks it breaking."""
    first, _, body = message.strip().partition("\n")
    first = first.strip()
    breaking = bool(_BREAKING.search(message))
    match = _HEADER.match(first)
    if not match:
        return Change(type="other", breaking=breaking, group=None, description=first)
    ctype = match.group("type").lower()
    if match.group("bang"):
        breaking = True
    desc = match.group("desc").strip()
    return Change(
        type=ctype,
        breaking=breaking,
        group=_TYPE_GROUP.get(ctype),
        description=desc,
    )


def _bump_level(changes: list[Change]) -> str:
    if any(c.breaking for c in changes):
        return "major"
    if any(c.type == "feat" for c in changes):
        return "minor"
    if changes:
        return "patch"
    return "none"


def next_version(current: str, changes: list[Change]) -> str:
    """Apply the strongest bump implied by ``changes`` to ``current`` (``MAJOR.MINOR.PATCH``,
    an optional leading ``v`` preserved). Pre-1.0.0, a breaking change bumps minor, not major
    (semver's 0.y.z rule). ``none`` (no changes) returns ``current`` unchanged. A trailing
    ``-prerelease`` / ``+build`` suffix on ``current`` is dropped before bumping (semver)."""
    prefix = "v" if current.startswith("v") else ""
    core = current[1:] if prefix else current
    core = re.split(r"[-+]", core, maxsplit=1)[0]  # drop a -prerelease / +build suffix
    try:
        major, minor, patch = (int(p) for p in core.split("."))
    except ValueError as exc:
        raise ValueError(f"not a MAJOR.MINOR.PATCH version: {current!r}") from exc
    level = _bump_level(changes)
    if level == "major":
        major, minor, patch = (major + 1, 0, 0) if major >= 1 else (0, minor + 1, 0)
    elif level == "minor":
        minor, patch = minor + 1, 0
    elif level == "patch":
        patch += 1
    return f"{prefix}{major}.{minor}.{patch}"


def changelog_groups(changes: list[Change]) -> dict[str, list[str]]:
    """Group change descriptions by Keep-a-Changelog section, in :data:`GROUP_ORDER`. A breaking
    change gets a ``**BREAKING:**`` prefix; uncategorised commits are omitted."""
    groups: dict[str, list[str]] = {}
    for change in changes:
        if change.group is None:
            continue
        entry = f"**BREAKING:** {change.description}" if change.breaking else change.description
        groups.setdefault(change.group, []).append(entry)
    return {g: groups[g] for g in GROUP_ORDER if g in groups}


def summarize(current: str, messages: list[str]) -> Summary:
    """Classify ``messages``, compute the next version and the grouped changelog, and collect the
    breaking-change descriptions — the structured proposal the ``release`` skill renders."""
    changes = [classify(m) for m in messages]
    return Summary(
        current=current,
        version=next_version(current, changes),
        bump=_bump_level(changes),
        groups=changelog_groups(changes),
        breaking=[c.description for c in changes if c.breaking],
    )


def commits_since(repo: Path | str, tag: str | None = None) -> list[str]:  # pragma: no cover
    """Return commit messages (subject + body) since ``tag`` (or the latest tag if ``None``),
    newest first. Thin ``git`` seam — the skill calls this; the pure core above is tested without
    a repo. Returns ``[]`` when there are no tags/commits or git is unavailable."""
    import subprocess

    repo = str(repo)

    def _git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", repo, *args], capture_output=True, text=True, check=True
        ).stdout

    try:
        if tag is None:
            tag = _git("describe", "--tags", "--abbrev=0").strip() or None
        rng = f"{tag}..HEAD" if tag else "HEAD"
        # %B = raw body; NUL-separate records so multi-line messages survive splitting.
        out = _git("log", rng, "--no-merges", "--format=%B%x00")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [chunk.strip() for chunk in out.split("\0") if chunk.strip()]
