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
    "next_calver",
    "looks_calver",
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
    prefix, core = _split_core(current)
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


def _split_core(current: str) -> tuple[str, str]:
    """(`v` prefix or "", the dotted core with any ``-prerelease``/``+build`` suffix dropped)."""
    prefix = "v" if current.startswith("v") else ""
    core = current[1:] if prefix else current
    return prefix, re.split(r"[-+]", core, maxsplit=1)[0]


def looks_calver(version: str) -> bool:
    """True when ``version`` is already CalVer (``YYYY.M.N``, ADR 0055) — the first component is a
    plausible year. Lets the ``release`` skill pick the repo's scheme mechanically."""
    _, core = _split_core(version)
    head = core.split(".", 1)[0]
    return head.isdigit() and int(head) >= 2000


def next_calver(current: str, *, year: int, month: int) -> str:
    """The next CalVer ``<year>.<month>.<inc>`` (ADR 0055): ``inc`` restarts at 1 in a new
    (year, month) and increments within one. ``year``/``month`` come from the caller's clock
    (UTC date of the release) so the function stays pure; a non-CalVer ``current`` (e.g. the
    pre-migration ``0.1.0``) simply starts the month's counter at 1. Month and inc carry **no
    zero-padding**, so the result is also a valid semver triple that sorts above any pre-migration
    ``0.x``/``1.x`` — upgrade flows that compare versions keep working."""
    prefix, core = _split_core(current)
    parts = core.split(".")
    inc = 1
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        cur_year, cur_month, cur_inc = (int(p) for p in parts)
        if (cur_year, cur_month) == (year, month):
            inc = cur_inc + 1
    return f"{prefix}{year}.{month}.{inc}"


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


def summarize(
    current: str, messages: list[str], *, calver: tuple[int, int] | None = None
) -> Summary:
    """Classify ``messages``, compute the next version and the grouped changelog, and collect the
    breaking-change descriptions — the structured proposal the ``release`` skill renders.

    ``calver=(year, month)`` switches the version scheme to CalVer (ADR 0055): the version becomes
    ``next_calver`` for that UTC date (unchanged when there are no changes to release), while
    ``bump`` still reports the semantic level — under CalVer it informs the changelog reader, not
    the version string, and breaking changes stay flagged in ``breaking``/the groups."""
    changes = [classify(m) for m in messages]
    level = _bump_level(changes)
    if calver is None:
        version = next_version(current, changes)
    elif level == "none":
        version = current  # nothing to release — same contract as the semver path
    else:
        version = next_calver(current, year=calver[0], month=calver[1])
    return Summary(
        current=current,
        version=version,
        bump=level,
        groups=changelog_groups(changes),
        breaking=[c.description for c in changes if c.breaking],
    )


def commits_since(repo: Path | str, tag: str | None = None) -> list[str]:
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
