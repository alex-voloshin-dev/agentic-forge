"""Where a feature's documents go in the target repository: detected, never configured.

A repository that already keeps its features somewhere (``features/in-progress/<slug>/``) and
numbers its decisions in a series (``adr-066``, ``ADR-G14``) must not get a second home for them
(``docs/sdlc/<slug>/``) or a colliding numbering. A repository's config may only switch things off
(ADR 0102/0103), so the convention is read from the tree, not declared:

- **The feature folder** is a directory named exactly ``<slug>`` that holds a feature document
  (:data:`FEATURE_ARTIFACTS`, case-insensitively). With none, ``docs/sdlc/<slug>/``; with several,
  the one holding the most such documents, then the shallowest, and ``ambiguous`` says so. A
  document keeps the spelling it has on disk (``PRD.md``), so a case-sensitive filesystem does not
  get a second one beside it.
- **An ADR series** is the set of files in one directory below the top sharing a numbering:
  ``adr-001-x.md``, ``ADR-G01-x.md`` (a letter prefix of one to three letters, then at least two
  digits), and, in a directory named ``adr``, ``adrs`` or ``decisions``, the bare ``0001-x.md`` of
  adr-tools (never a dated ``2024-01-15-x.md``). A series in a feature folder (the folder itself,
  or an ``adr``/``adrs``/``decisions`` directory directly in it) is that feature's own; every other
  one is shared. The feature's own series wins; else the shared series nearest the feature folder,
  by path distance. Equally near series, or shared series beside other features' own ones, make
  the answer ``ambiguous``: the skill asks, or records its pick as an assumption when headless.
  Other features' own series are never continued; when they are the only ones, this feature's
  starts at 1, spelled and placed as most of theirs are.

**Every path it proposes is safe to put on a command line.** A folder or series directory counts
only when each component of its path below the top matches :data:`SAFE_COMPONENT` (letters,
digits, ``.``, ``_``, ``-``, not starting with ``-`` or ``.``); one that does not is skipped and
named in ``ambiguities``. :func:`home` also reports, per document, whether something other than a
regular file sits at its path or a symlink on the way to it (``unsafe``), so nothing is written
through a link.

The walk is bounded (:data:`MAX_DEPTH`, :data:`MAX_ENTRIES`; ``truncated`` says when a cap cut it,
the depth cap included, and a truncated walk is ``ambiguous``), breadth-first so the shallow tree
is read first, and skips hidden directories (``.git``, ``.claude/worktrees``), dependency and build
output (:data:`SKIP_DIRS`, unless the directory is named exactly ``<slug>``) and any nested
repository (a directory holding a ``.git`` entry). It never follows a symlink. The core
(:func:`resolve`) is pure over a :class:`Scan`; :func:`scan` and :func:`home` are the I/O. Stdlib
only and reachable from the role-scope hook, which reads :func:`dir_names`, :func:`marks_feature`
and :func:`holds_series`: Python 3.9.
"""

from __future__ import annotations

import errno
import os
import re
import stat
from collections import Counter, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "ADR_DIR_NAMES",
    "DOCUMENT_KINDS",
    "FALLBACK_ROOT",
    "FEATURE_ARTIFACTS",
    "KIND_FILES",
    "KIND_TYPES",
    "KINDS",
    "MAX_DEPTH",
    "MAX_DIR_ENTRIES",
    "MAX_ENTRIES",
    "REVIEW_KINDS",
    "SAFE_COMPONENT",
    "SKIP_DIRS",
    "SLUG_RE",
    "AdrFile",
    "Scan",
    "Series",
    "adr_file",
    "artifact_format",
    "dir_names",
    "feature_dirs",
    "holds_adr_series",
    "holds_series",
    "home",
    "is_feature_dir",
    "is_safe_path",
    "marks_feature",
    "relative_document",
    "resolve",
    "review_files",
    "scan",
    "series_of",
]

# The documents that make a directory a feature's folder: the plugin's, and the names a
# repository's own feature folders were seen to use (`design.md` beside `tech-design.md`).
FEATURE_ARTIFACTS = frozenset(
    {"prd.md", "plan.md", "design.md", "tech-design.md", "research-brief.md", "ux-spec.md"}
)
# The same shape doc_delivery.SLUG_RE has (a test keeps them equal): a slug names a branch too.
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# What a directory component must look like to be proposed: nothing a shell could act on, no
# leading `-` an argument parser could read as an option, no leading `.`.
SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\Z")
FALLBACK_ROOT = "docs/sdlc"
KIND_FILES = {
    "research": "research-brief.md",
    "prd": "prd.md",
    "design": "tech-design.md",
    "plan": "plan.md",
    "ux": "ux-spec.md",
}
KIND_TYPES = {
    "research": "research-brief", "prd": "prd", "design": "tech-design", "plan": "plan",
    "ux": "ux-spec",
}
# The external reviewer's `--kind` for each document.
REVIEW_KINDS = {
    "research": "research", "prd": "product", "design": "technical", "plan": "plan", "ux": "ux",
}
DOCUMENT_KINDS = ("research", "prd", "design", "plan", "ux")
KINDS = (*DOCUMENT_KINDS, "adr")
ADR_DIR_NAMES = frozenset({"adr", "adrs", "decisions"})
# Dependency trees and build output: large, generated, and never where a team keeps its documents.
SKIP_DIRS = frozenset({
    "node_modules", "vendor", "build", "dist", "out", "target", "__pycache__", "venv",
    "site-packages", "bower_components", "coverage", "htmlcov",
})
MAX_DEPTH = 12
MAX_ENTRIES = 200_000
# What one directory is read up to when a single directory is asked about (the role-scope hook).
MAX_DIR_ENTRIES = 10_000
_MAX_SERIES_REPORTED = 20
_MAX_SHOWN = 80
_FORMAT_PROBE_BYTES = 64 * 1024

# `adr-001-title.md`, `ADR-G14-title.md`, `adr_0042.md`. A letter prefix needs two digits or more,
# so `adr-db2-migration.md` is a title, not series DB.
_ADR_NAMED = re.compile(
    r"^(?P<lead>adr)(?P<sep>[-_]?)(?P<prefix>[a-z]{0,3}?)(?P<num>\d+)(?P<rest>[-_.][^/]*)?\.md$",
    re.IGNORECASE,
)
# adr-tools' `0001-record-architecture-decisions.md`, only in a directory named for decisions.
_ADR_BARE = re.compile(r"^(?P<num>\d{3,5})(?P<rest>[-_][^/]*)?\.md$", re.IGNORECASE)
# A dated note (`2024-01-15-x.md`, `2024_03-x.md`) is not a decision record's number.
_DATED = re.compile(r"^\d{4}[-_]\d{1,2}(?:[-_.]|\Z)")


@dataclass(frozen=True)
class AdrFile:
    """One file of a numbered decision series."""

    lead: str  # `adr`, `ADR`, or "" for the bare form
    sep: str  # between the lead and the prefix
    prefix: str  # the series letters as written (`G`), "" for the main series
    number: int
    width: int  # digits as written, so `066` continues as `067`
    title_sep: str  # what follows the number before the title

    @property
    def key(self) -> str:
        return "#bare" if not self.lead else self.prefix.upper()

    def ident(self, number: int | None = None) -> str:
        value = self.number if number is None else number
        return f"{self.lead}{self.sep}{self.prefix}{str(value).zfill(self.width)}"

    def pattern(self) -> str:
        return f"{self.lead}{self.sep}{self.prefix}{'N' * self.width}{self.title_sep}<title>.md"

    def file_name(self, number: int) -> str:
        return f"{self.ident(number)}{self.title_sep}<title>.md"


def adr_file(name: str, directory_name: str = "") -> AdrFile | None:
    """The series member ``name`` is, in a directory called ``directory_name``, or None."""
    match = _ADR_NAMED.match(name)
    if match:
        prefix, num = match.group("prefix"), match.group("num")
        if prefix and len(num) < 2:
            return None
        rest = match.group("rest") or ""
        return AdrFile(
            match.group("lead"), match.group("sep"), prefix, int(num), len(num),
            rest[:1] if rest[:1] in ("-", "_") else "-",
        )
    if directory_name.casefold() in ADR_DIR_NAMES and not _DATED.match(name):
        bare = _ADR_BARE.match(name)
        if bare:
            num, rest = bare.group("num"), bare.group("rest") or ""
            return AdrFile("", "", "", int(num), len(num), rest[:1] or "-")
    return None


def is_safe_path(rel: str) -> bool:
    """Every component of ``rel`` (``/``-separated, "" for the top) is :data:`SAFE_COMPONENT`."""
    return rel == "" or all(SAFE_COMPONENT.match(part) for part in rel.split("/"))


def _shown(rel: str) -> str:
    text = repr(rel)
    return text if len(text) <= _MAX_SHOWN else text[: _MAX_SHOWN - 1] + "…"


def _relevant(name: str, directory_name: str) -> bool:
    folded = name.casefold()
    if not folded.endswith(".md"):
        return False
    return (
        folded in FEATURE_ARTIFACTS
        or folded.startswith("review")
        or adr_file(name, directory_name) is not None
    )


@dataclass(frozen=True)
class Scan:
    """What a walk found: each directory (relative, ``/``-separated, "" for the top) holding a
    relevant Markdown file, with those files' names; whether the entry cap cut the walk short, and
    whether the depth cap left a directory unread."""

    dirs: Mapping[str, tuple[str, ...]]
    truncated: bool = False
    depth_capped: bool = False


@dataclass(frozen=True)
class Series:
    """One numbered decision series: where it lives and how it continues."""

    dir: str
    style: AdrFile  # the highest-numbered member, whose spelling the next one copies
    count: int
    owner: str | None  # the feature folder it belongs to, or None for a shared series

    @property
    def highest(self) -> str:
        return self.style.ident()

    @property
    def next_id(self) -> str:
        return self.style.ident(self.style.number + 1)


# --- the walk -------------------------------------------------------------------------------------


def _join(parent: str, name: str) -> str:
    return f"{parent}/{name}" if parent else name


def scan(
    repo: str, *, max_depth: int = MAX_DEPTH, max_entries: int = MAX_ENTRIES,
    keep: str | None = None,
) -> Scan:
    """Walk ``repo`` breadth-first within the caps, never through a symlink. A directory that
    cannot be read is skipped, as is one holding a ``.git`` entry below the top (another
    repository). A directory named ``keep`` (the slug) is read even when :data:`SKIP_DIRS` names
    it."""
    root = os.path.realpath(repo)
    found: dict[str, tuple[str, ...]] = {}
    queue: deque[tuple[str, int]] = deque([("", 0)])
    budget = max_entries
    depth_capped = False
    while queue:
        rel, depth = queue.popleft()
        path = os.path.join(root, *rel.split("/")) if rel else root
        entries: list[os.DirEntry[str]] = []
        try:
            with os.scandir(path) as listing:
                for entry in listing:
                    budget -= 1
                    if budget < 0:
                        return Scan(found, truncated=True, depth_capped=depth_capped)
                    entries.append(entry)
        except OSError:
            continue
        if rel and any(entry.name == ".git" for entry in entries):
            continue  # a submodule or a nested clone: not this repository's documents
        here = rel.rsplit("/", 1)[-1]
        names: list[str] = []
        subdirs: list[str] = []
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name.casefold() in SKIP_DIRS and entry.name != keep:
                        continue
                    if depth < max_depth:
                        subdirs.append(entry.name)
                    else:
                        depth_capped = True
                elif entry.is_file(follow_symlinks=False) and _relevant(entry.name, here):
                    names.append(entry.name)
            except OSError:
                continue
        if names:
            found[rel] = tuple(sorted(names))
        queue.extend((_join(rel, name), depth + 1) for name in sorted(subdirs))
    return Scan(found, depth_capped=depth_capped)


# --- the pure core --------------------------------------------------------------------------------


def _artifacts(names: Sequence[str]) -> list[str]:
    return sorted(name for name in names if name.casefold() in FEATURE_ARTIFACTS)


def feature_dirs(found: Scan) -> list[str]:
    """Every directory holding a feature document, whatever its name."""
    return sorted(d for d, names in found.dirs.items() if _artifacts(names))


def review_files(found: Scan) -> list[str]:
    """The ``review*.md`` files beside a feature document: where the review loops write rounds."""
    out: list[str] = []
    for directory in feature_dirs(found):
        out += [
            _join(directory, name) for name in found.dirs[directory]
            if name.casefold().startswith("review")
        ]
    return out


def _depth(path: str) -> int:
    return len(path.split("/")) if path else 0


def _distance(a: str, b: str) -> int:
    pa, pb = (a.split("/") if a else []), (b.split("/") if b else [])
    common, limit = 0, min(len(pa), len(pb))
    while common < limit and pa[common] == pb[common]:
        common += 1
    return len(pa) + len(pb) - 2 * common


def _owner(directory: str, features: set[str]) -> str | None:
    """The feature folder a series in ``directory`` belongs to: the folder itself, or the one an
    ``adr``/``adrs``/``decisions`` directory sits directly in. The top is nobody's."""
    if directory and directory in features:
        return directory
    parent, _, name = directory.rpartition("/")
    if parent and name.casefold() in ADR_DIR_NAMES and parent in features:
        return parent
    return None


def series_of(found: Scan) -> list[Series]:
    """Every numbered decision series in the scan below the top (a record at the top is not in a
    directory the architect may write), sorted by directory, then the main series."""
    features = set(feature_dirs(found))
    out: list[Series] = []
    for directory in sorted(found.dirs):
        if not directory:
            continue
        here = directory.rsplit("/", 1)[-1]
        groups: dict[str, list[AdrFile]] = {}
        for name in found.dirs[directory]:
            member = adr_file(name, here)
            if member is not None:
                groups.setdefault(member.key, []).append(member)
        for key in sorted(groups):
            members = groups[key]
            style = max(members, key=lambda m: (m.number, m.width))
            out.append(Series(directory, style, len(members), _owner(directory, features)))
    return out


def _series_view(series: Series, feature_dir: str) -> dict[str, Any]:
    return {
        "dir": series.dir,
        "pattern": series.style.pattern(),
        "highest": series.highest,
        "next_id": series.next_id,
        "count": series.count,
        "scope": "shared" if series.owner is None else "feature",
        "distance": _distance(feature_dir, series.dir),
    }


def _unsafe_reason(rel: str, what: str) -> str:
    return (
        f"skipped {what} {_shown(rel)}: its path holds a character a shell could act on (only "
        "letters, digits, '.', '_' and '-' are proposed)"
    )


def _choose_feature(found: Scan, slug: str) -> tuple[str, bool, list[str], list[str]]:
    """The feature folder, whether it was detected, the candidates, and why it is ambiguous."""
    named = [d for d in feature_dirs(found) if d.rsplit("/", 1)[-1] == slug]
    why = [_unsafe_reason(d, "a feature folder") for d in named if not is_safe_path(d)]
    candidates = [d for d in named if is_safe_path(d)]
    if not candidates:
        return f"{FALLBACK_ROOT}/{slug}", False, [], why
    ranked = sorted(
        candidates, key=lambda d: (-len(_artifacts(found.dirs[d])), _depth(d), d)
    )
    if len(ranked) > 1:
        why.append(
            f"{len(ranked)} folders named {slug} hold feature documents: {', '.join(ranked)}; "
            f"chose {ranked[0]}"
        )
    return ranked[0], True, ranked, why


def _most_common(counts: Counter[Any]) -> Any:
    """The most frequent key; a tie goes to the smallest, so the answer does not depend on order."""
    return sorted(counts.items(), key=lambda kv: (-kv[1], repr(kv[0])))[0][0]


def _choose_adr(found: Scan, feature_dir: str, detected: bool) -> tuple[dict[str, Any], list[str]]:
    why: list[str] = []
    every: list[Series] = []
    for series in series_of(found):
        if is_safe_path(series.dir):
            every.append(series)
        elif _unsafe_reason(series.dir, "an ADR series in") not in why:
            why.append(_unsafe_reason(series.dir, "an ADR series in"))
    own = [s for s in every if detected and s.owner == feature_dir]
    shared = [s for s in every if s.owner is None]
    others = [s for s in every if s.owner is not None and s.owner != feature_dir]
    listed = sorted(every, key=lambda s: (_distance(feature_dir, s.dir), s.dir, s.style.key))
    report: dict[str, Any] = {
        "series_count": len(every),
        "series": [_series_view(s, feature_dir) for s in listed[:_MAX_SERIES_REPORTED]],
    }
    pool = own or shared
    if pool:
        nearest = min(_distance(feature_dir, s.dir) for s in pool)
        tied = [s for s in listed if s in pool and _distance(feature_dir, s.dir) == nearest]
        chosen = tied[0]
        if len(tied) > 1:
            why.append(
                f"{len(tied)} ADR series are equally near {feature_dir}: "
                + ", ".join(f"{s.dir}/{s.style.pattern()}" for s in tied)
                + f"; chose {chosen.dir}/{chosen.style.pattern()}"
            )
        if not own and others:
            why.append(
                "a shared ADR series and feature-local ADR folders both exist; chose the shared "
                f"{chosen.dir}"
            )
        report.update({
            "dir": chosen.dir, "detected": True,
            "scope": "feature" if own else "shared",
            "pattern": chosen.style.pattern(), "highest": chosen.highest,
            "next_id": chosen.next_id,
            "next_file": chosen.style.file_name(chosen.style.number + 1), "create_dir": False,
        })
        return report, why
    if others:
        # Only other features keep ADRs, each its own: start this feature's at 1, spelled and
        # placed (in the folder, or in an adr/adrs/decisions directory in it) as most of theirs.
        styles = Counter(
            (s.style.lead, s.style.sep, s.style.prefix, s.style.width, s.style.title_sep)
            for s in others
        )
        lead, sep, prefix, width, title_sep = _most_common(styles)
        sub = _most_common(Counter(
            "" if s.dir == s.owner else s.dir.rsplit("/", 1)[-1] for s in others
        ))
        first = AdrFile(lead, sep, prefix, 0, width, title_sep)
        report.update({
            "dir": _join(feature_dir, sub) if sub else feature_dir, "detected": True,
            "scope": "feature", "pattern": first.pattern(), "highest": None,
            "next_id": first.ident(1), "next_file": first.file_name(1), "create_dir": bool(sub),
        })
        return report, why
    report.update({
        "dir": feature_dir, "detected": False, "scope": "none",
        "pattern": "adr-<decision>.md", "highest": None, "next_id": None,
        "next_file": "adr-<decision>.md", "create_dir": False,
    })
    return report, why


def _spelling(found: Scan, feature_dir: str, kind: str, why: list[str]) -> str:
    """The name ``kind``'s document has in ``feature_dir`` (``PRD.md``), or the plugin's own when
    there is none. Several case variants are an ambiguity."""
    canonical = KIND_FILES[kind]
    variants = sorted(
        name for name in found.dirs.get(feature_dir, ()) if name.casefold() == canonical
    )
    if not variants:
        return canonical
    chosen = canonical if canonical in variants else variants[0]
    if len(variants) > 1:
        why.append(
            f"{len(variants)} spellings of {canonical} in {feature_dir}: {', '.join(variants)}; "
            f"chose {chosen}"
        )
    return chosen


def resolve(found: Scan, slug: str, kind: str | None = None) -> dict[str, Any]:
    """Where ``slug``'s documents go, from a :class:`Scan`. Pure; the documents' on-disk state is
    added by :func:`home`."""
    if not SLUG_RE.match(slug):
        raise ValueError(f"invalid feature slug {slug!r}: expected {SLUG_RE.pattern}")
    if kind is not None and kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; expected one of: {', '.join(KINDS)}")
    feature_dir, detected, candidates, why = _choose_feature(found, slug)
    adr, adr_why = _choose_adr(found, feature_dir, detected)
    why += adr_why
    documents = {
        name: {"path": _join(feature_dir, _spelling(found, feature_dir, name, why))}
        for name in DOCUMENT_KINDS
    }
    if found.truncated:
        why.append(
            f"the walk stopped at its cap of {MAX_ENTRIES} entries: a folder or series further in "
            "was not seen"
        )
    if found.depth_capped:
        why.append(
            f"the walk did not read below depth {MAX_DEPTH}: a folder or series deeper in was not "
            "seen"
        )
    result: dict[str, Any] = {
        "slug": slug,
        "feature_dir": feature_dir,
        "detected": detected,
        "feature_candidates": candidates,
        "existing": _artifacts(found.dirs.get(feature_dir, ())),
        "documents": documents,
        "adr": adr,
        "ambiguous": bool(why),
        "ambiguities": why,
        "truncated": found.truncated or found.depth_capped,
    }
    if kind == "adr":
        result["artifact"] = {"kind": kind, "path": _join(adr["dir"], adr["next_file"])}
    elif kind is not None:
        result["artifact"] = {"kind": kind, **documents[kind]}
    return result


def artifact_format(text: str, artifact_type: str) -> str:
    """``handoff`` when ``text`` opens with a ``---`` frontmatter fence whose ``type`` is
    ``artifact_type``; ``foreign`` for anything else (a metadata table, another tool's header)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "foreign"
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, _, value = line.partition(":")
        if key.strip() == "type" and value.strip().strip("'\"") == artifact_type:
            return "handoff"
    return "foreign"


# --- the I/O around it ----------------------------------------------------------------------------


def _regular_text(path: str, limit: int) -> str | None:
    """The start of a regular file, not through a symlink; None when there is none."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            return None
        return handle.read(limit).decode("utf-8", errors="replace")


def _state(root: str, rel: str, want_dir: bool) -> tuple[bool, str | None]:
    """Whether something is at ``rel`` below ``root``, and why writing there is unsafe, or None:
    a symlink or a non-directory on the way, or, at the end, a symlink or anything that is not a
    regular file (a directory for ``want_dir``). Nothing followed: each step is an ``lstat``."""
    parts = rel.split("/") if rel else []
    current = root
    for index, part in enumerate(parts):
        current = os.path.join(current, part)
        so_far = "/".join(parts[: index + 1])
        try:
            info = os.lstat(current)
        except OSError as exc:
            if exc.errno in (errno.ENOENT, errno.ENOTDIR):
                return False, None
            return True, f"cannot be inspected: {so_far}"
        last = index == len(parts) - 1
        if stat.S_ISLNK(info.st_mode):
            return True, f"symlink: {so_far}"
        if not last and not stat.S_ISDIR(info.st_mode):
            return True, f"not a directory: {so_far}"
        if last:
            if want_dir and not stat.S_ISDIR(info.st_mode):
                return True, f"not a directory: {so_far}"
            if not want_dir and not stat.S_ISREG(info.st_mode):
                kind = "directory" if stat.S_ISDIR(info.st_mode) else "not a regular file"
                return True, f"{kind}: {so_far}"
    return bool(parts), None


def _work_tree_top(path: str) -> str | None:
    """The nearest directory at or above ``path`` holding a ``.git`` entry, or None."""
    current = path
    while True:
        if os.path.lexists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def relative_document(root: str, path: str) -> str:
    """The repository-relative path of a document the user named: relative to ``root``, or, for an
    absolute path, relative to the working tree holding it (the main checkout's
    ``/home/u/repo/features/x/prd.md`` is ``features/x/prd.md`` in any of its worktrees). Refused
    unless every component is :data:`SAFE_COMPONENT` and it names a Markdown file."""
    if os.path.isabs(path):
        absolute = os.path.normpath(path)
        top = _work_tree_top(os.path.dirname(absolute))
        if top is None:
            raise ValueError(f"--path {_shown(path)} is not inside a git working tree")
        rel = os.path.relpath(absolute, top)
    else:
        rel = os.path.normpath(path)
    rel = rel.replace(os.sep, "/")
    if rel.startswith("../") or rel in ("..", ".") or not is_safe_path(rel):
        raise ValueError(
            f"--path {_shown(path)} must name a file in the repository whose path holds only "
            "letters, digits, '.', '_' and '-'"
        )
    if not rel.casefold().endswith(".md"):
        raise ValueError(f"--path {_shown(path)} is not a Markdown document")
    return rel


def _on_disk(root: str, entry: dict[str, Any], artifact_type: str | None) -> None:
    rel = entry["path"]
    entry["abs"] = os.path.join(root, *rel.split("/"))
    exists, unsafe = _state(root, rel, want_dir=False)
    entry["exists"] = exists
    if unsafe:
        entry["unsafe"] = unsafe
    if artifact_type is not None:
        text = None if unsafe or not exists else _regular_text(entry["abs"], _FORMAT_PROBE_BYTES)
        entry["format"] = None if text is None else artifact_format(text, artifact_type)


def home(
    repo: str, slug: str, kind: str | None = None, path: str | None = None
) -> dict[str, Any]:
    """:func:`resolve` over a walk of ``repo``, with each document's absolute path, ``exists``,
    ``format``, and ``unsafe`` when something other than a regular file is at its path or a symlink
    is on the way. ``path`` is a document the user named for ``kind``
    (:func:`relative_document`)."""
    root = os.path.realpath(repo)
    result = resolve(scan(root, keep=slug), slug, kind)
    if path is not None:
        if kind not in DOCUMENT_KINDS:
            raise ValueError("--path needs --kind of a document: " + ", ".join(DOCUMENT_KINDS))
        result["documents"][kind] = {"path": relative_document(root, path), "named": True}
        result["artifact"] = {"kind": kind, **result["documents"][kind]}
    result["repo"] = root
    result["feature_abs"] = os.path.join(root, *result["feature_dir"].split("/"))
    for name, entry in result["documents"].items():
        _on_disk(root, entry, KIND_TYPES[name])
    adr = result["adr"]
    adr["abs_dir"] = os.path.join(root, *adr["dir"].split("/"))
    exists, unsafe = _state(root, adr["dir"], want_dir=True)
    adr["dir_exists"] = exists
    if unsafe:
        adr["unsafe"] = unsafe
    artifact = result.get("artifact")
    if artifact is not None:
        if kind == "adr":
            artifact["abs"] = os.path.join(root, *artifact["path"].split("/"))
            artifact["exists"] = False
            if unsafe:
                artifact["unsafe"] = unsafe
        else:
            artifact.update(result["documents"][kind or ""])
    return result


# --- what the role-scope hook asks about one directory --------------------------------------------


def dir_names(directory: str) -> list[str] | None:
    """The regular files' names in ``directory`` (not symlinks), within :data:`MAX_DIR_ENTRIES`;
    None when it cannot be read or holds more. One listing, for both predicates below."""
    names: list[str] = []
    try:
        with os.scandir(directory) as listing:
            for count, entry in enumerate(listing):
                if count >= MAX_DIR_ENTRIES:
                    return None
                if entry.is_file(follow_symlinks=False):
                    names.append(entry.name)
    except OSError:
        return None
    return names


def marks_feature(names: Sequence[str], directory_name: str) -> bool:
    """A directory called ``directory_name`` holding ``names`` is a feature folder: named like a
    slug, holding a feature document."""
    return bool(SLUG_RE.match(directory_name)) and any(
        name.casefold() in FEATURE_ARTIFACTS for name in names
    )


def holds_series(names: Sequence[str], directory_name: str) -> bool:
    """A directory called ``directory_name`` holding ``names`` holds a numbered decision record."""
    return any(adr_file(name, directory_name) is not None for name in names)


def is_feature_dir(directory: str) -> bool:
    """``directory`` (absolute, resolved) is a feature folder, read with one listing."""
    names = dir_names(directory)
    return names is not None and marks_feature(names, os.path.basename(directory))


def holds_adr_series(directory: str) -> bool:
    """``directory`` (absolute, resolved) holds a member of a numbered decision series."""
    names = dir_names(directory)
    return names is not None and holds_series(names, os.path.basename(directory))
