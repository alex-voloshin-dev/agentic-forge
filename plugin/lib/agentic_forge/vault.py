"""Obsidian-format knowledge vault for a target repo (ADR 0018).

The vault lives at ``<repo>/docs/knowledge/``: atomic **notes** (kebab-case ``.md``, YAML
frontmatter + a ``[[wikilink]]`` body), **maps-of-content** (``type: moc``), and a root map as
the entry point (``MOC.md``, else ``INDEX.md``, ``Home.md`` or ``README.md``). Notes are read from
every folder below the vault, as Obsidian does, and a note's name is its file stem wherever it
sits; :func:`load_vault` says what the walk skips and where it stops. This module is the
deterministic, tested core — parse/resolve
wikilinks, load the note graph, **validate** it (broken links, orphans, missing root MOC),
**scaffold** an empty vault, **add+link** a note, **rank recall candidates** for a query, and
build the **session-start summary**. The *semantic* last mile (which candidates matter, how to
synthesise) belongs to the ``knowledge`` skill.
"""

from __future__ import annotations

import errno
import json
import os
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from agentic_forge import settings, state_io
from agentic_forge.frontmatter import FrontmatterError
from agentic_forge.frontmatter import parse as parse_frontmatter

__all__ = [
    "VAULT_DIRNAME",
    "ROOT_MOC",
    "ROOT_MAP_NAMES",
    "Note",
    "Vault",
    "vault_path",
    "wikilink",
    "parse_links",
    "load_vault",
    "validate_vault",
    "scaffold",
    "add_note",
    "note_path",
    "recall",
    "recall_notes",
    "session_summary",
    "outside_repo_notice",
]

VAULT_DIRNAME = "docs/knowledge"
ROOT_MOC = "MOC"  # the root map-of-content note scaffold writes, MOC.md
# The names a root map may have at the vault root, in precedence order, matched without regard to
# case. MOC is ours; INDEX and Home are what Obsidian vaults kept by hand use; README is GitHub's.
# README.md is the vault's meta-doc, not a note, so it is the map only when none of the others is
# there, and nothing here ever writes to it.
ROOT_MAP_NAMES = (ROOT_MOC, "INDEX", "Home", "README")
_WRITABLE_ROOT_MAPS = ROOT_MAP_NAMES[:-1]
_README = "readme.md"
_MAX_NOTE_BYTES = 2 * 1024 * 1024  # what a handoff artifact may be: past it, not parsed
# The walk is bounded: it runs on every session start, in a repo nobody vetted. A vault past any of
# these loads what it reached (shallowest folders first) and validate_vault says it stopped.
_MAX_DEPTH = 8  # folders below the vault root; a note deeper than that is not read
_MAX_NOTES = 5000  # note files read
_MAX_WALK_ENTRIES = 20000  # directory entries looked at, of any kind
_MAX_VAULT_BYTES = 32 * 1024 * 1024  # bytes of note files read, in all, charged before parsing
_MAX_FRONTMATTER_CHARS = 64 * 1024  # a frontmatter block longer than this is not parsed as YAML
_SUMMARY_TITLE_CHARS = 120  # a title in the session-start summary, past which it is cut

# [[target]] | [[target|alias]] | [[target#heading]] | [[target#heading|alias]] -> target
# (newlines excluded so a stray "[[" can't swallow text across lines into a bogus target)
_WIKILINK = re.compile(r"\[\[([^\[\]|#\n]+?)(?:#[^\[\]|\n]+)?(?:\|[^\[\]\n]+)?\]\]")
_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an the of to and or for in on at by is are be with from this that it as we our".split()
)


@dataclass(frozen=True)
class Note:
    name: str  # file stem (kebab-case); the wikilink target
    title: str
    type: str  # "note" | "moc"
    tags: tuple[str, ...]
    body: str
    links: tuple[str, ...]  # outgoing wikilink targets, as written
    path: Path


@dataclass(frozen=True)
class Vault:
    repo: Path
    notes: dict[str, Note]  # keyed by lower-cased name for case-insensitive resolution
    root: str | None = None  # the key of the root map in ``notes``, if the vault has one
    shadowed: tuple[Path, ...] = ()  # files not read because a note of their name was
    truncated: bool = False  # the walk stopped at a cap, so some notes were not read


def vault_path(repo: Path | str) -> Path:
    return Path(repo) / VAULT_DIRNAME


_OUTSIDE = (
    "the vault resolves outside the repo: keep it inside, or set knowledge.allow_external_vault "
    "in ~/.agentic-forge/config.json"
)


def _boundary(repo: Path | str) -> str:
    """What "inside the repo" is measured against: the nearest ancestor of ``repo`` holding a
    ``.git`` entry, since ``repo`` is often the session's working directory, a package inside the
    checkout. With none, ``repo`` itself. Deliberately not ``diagnostics.main_repo_root``, which
    follows a ``.git`` file's pointer to wherever it says: a linked worktree is its own boundary."""
    real = os.path.realpath(repo)
    current = real
    while not os.path.lexists(os.path.join(current, ".git")):
        parent = os.path.dirname(current)
        if parent == current:
            return real
        current = parent
    return current


def _vault_allowed(repo: Path | str) -> bool:
    """True if the vault directory resolves to the repo or below it, however it gets there, or the
    operator allows otherwise (ADR 0102). A plain path rule, so it does not matter who made a link
    or what tracks it, and it starts no process: the session-start hook comes through here."""
    boundary = _boundary(repo)
    real_vault = os.path.realpath(vault_path(repo))
    if real_vault == boundary or real_vault.startswith(boundary.rstrip(os.sep) + os.sep):
        return True
    return settings.resolve(repo).knowledge_allow_external_vault


def outside_repo_notice(repo: Path | str) -> str:
    """One line if a vault directory is not being read because it resolves outside the repo, else
    "". So that a vault kept elsewhere does not vanish silently on upgrade. Constant text: no path
    or name from the repo reaches the session through it."""
    if not vault_path(repo).is_dir() or _vault_allowed(repo):
        return ""
    return (
        f"agentic-forge: {VAULT_DIRNAME}/ resolves outside this repo, so it is not read. If you "
        "keep your vault elsewhere, set knowledge.allow_external_vault in "
        "~/.agentic-forge/config.json."
    )


def wikilink(name: str, alias: str | None = None) -> str:
    return f"[[{name}|{alias}]]" if alias else f"[[{name}]]"


def parse_links(text: str) -> list[str]:
    """The wikilink targets in ``text`` (deduped, order-preserved), without aliases/anchors."""
    seen: dict[str, None] = {}
    for match in _WIKILINK.finditer(text):
        seen.setdefault(match.group(1).strip(), None)
    return list(seen)


def _tokens(*parts: str) -> set[str]:
    out: set[str] = set()
    for part in parts:
        out.update(t for t in _WORD.findall(part.lower()) if t not in _STOPWORDS)
    return out


def _string_tags(tags: object) -> list[str]:
    """The strings in a note's ``tags``, whether it holds a list or a single one."""
    if isinstance(tags, str):
        return [tags]
    return [tag for tag in tags if isinstance(tag, str)] if isinstance(tags, list) else []


@dataclass(frozen=True)
class _Walk:
    files: tuple[Path, ...]  # note candidates, shallowest first, then by path
    readme: Path | None  # README.md at the vault root, a root map only when nothing else is
    truncated: bool


def _walk(vpath: Path) -> _Walk:
    """The ``.md`` files below ``vpath``, breadth first, in the order a name is resolved: a file
    nearer the root wins, then the lower path. Skipped: anything whose name starts with ``.``
    (``.obsidian``, ``.git``, ``.trash``), a folder whose name starts with ``_`` (Obsidian's
    convention for templates and attachments), every ``README.md`` (a folder's meta-doc; the root
    one is returned apart), and every symlink, file or folder: a link is never followed, so the walk
    cannot leave the vault or loop. Bounded by ``_MAX_DEPTH``, ``_MAX_NOTES`` and
    ``_MAX_WALK_ENTRIES``; hitting one sets ``truncated`` (the depth cap only for a folder past it
    that holds something). The entry cap can stop partway through a folder, and which of its
    entries were looked at by then is the filesystem's listing order, not name order."""
    found: list[tuple[int, str, Path]] = []
    readme: Path | None = None
    truncated = False
    seen = 0
    queue: deque[tuple[Path, int]] = deque([(vpath, 0)])
    while queue:
        directory, depth = queue.popleft()
        entries: list[os.DirEntry[str]] = []
        try:
            with os.scandir(directory) as listing:
                for entry in listing:
                    seen += 1
                    if seen > _MAX_WALK_ENTRIES:
                        truncated = True
                        break
                    entries.append(entry)
        except OSError:
            continue  # an unreadable folder costs its notes, not the vault
        for entry in sorted(entries, key=lambda e: e.name):
            name = entry.name
            try:
                if name.startswith(".") or entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if name.startswith("_"):
                        continue
                    if depth >= _MAX_DEPTH:
                        truncated = truncated or _has_entries(entry.path)
                        continue
                    queue.append((Path(entry.path), depth + 1))
                elif name.endswith(".md") and entry.is_file(follow_symlinks=False):
                    if name.lower() == _README:
                        if depth == 0 and readme is None:
                            readme = Path(entry.path)
                        continue
                    if len(found) >= _MAX_NOTES:
                        truncated = True
                        continue
                    path = Path(entry.path)
                    found.append((depth, path.relative_to(vpath).as_posix(), path))
            except OSError:
                continue
        if seen > _MAX_WALK_ENTRIES or (truncated and len(found) >= _MAX_NOTES):
            break  # nothing more would be read
    found.sort(key=lambda item: (item[0], item[1]))
    return _Walk(files=tuple(path for _, _, path in found), readme=readme, truncated=truncated)


def _has_entries(directory: str) -> bool:
    """True if ``directory`` holds anything: one entry looked at, not a walk."""
    try:
        with os.scandir(directory) as listing:
            return next(listing, None) is not None
    except OSError:
        return False


def _note_size(md: Path, vpath: Path) -> int | None:
    """The bytes reading ``md`` costs, or None if it is not read at all: a link (another file,
    whose frontmatter must not reach a session), not a regular file, or past ``_MAX_NOTE_BYTES``."""
    if not state_io.readable(md, vpath):
        return None
    try:
        size = md.stat().st_size
    except OSError:
        return None
    return None if size > _MAX_NOTE_BYTES else size


def _note_text(md: Path) -> str | None:
    """The text of ``md``, never read past ``_MAX_NOTE_BYTES`` (the file may have grown since it
    was measured), or None. A note that cannot be read as UTF-8 is None: one file in a repo must
    not take the rest of a session's context with it. Whether ``md`` is a link is the caller's
    check, :func:`_note_size`."""
    try:
        with open(md, "rb") as handle:
            raw = handle.read(_MAX_NOTE_BYTES + 1)
    except OSError:
        return None
    if len(raw) > _MAX_NOTE_BYTES:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _read_note(md: Path, vpath: Path) -> Note | None:
    """The note in ``md``, or None if it is not one this module reads (see :func:`_note_size` and
    :func:`_note_text`). For a caller that does not count what it reads; ``load_vault`` does."""
    text = _note_text(md) if _note_size(md, vpath) is not None else None
    return None if text is None else _parse_note(md, text)


def _parse_note(md: Path, text: str) -> Note:
    """The note ``text`` holds. Frontmatter is parsed as YAML only when its block closes within
    ``_MAX_FRONTMATTER_CHARS``: real frontmatter is a few lines, and pure-Python YAML on a 2 MiB
    block is where a session's start-up time would go. Past that the note has no frontmatter."""
    fm: dict[str, object]
    # Search from the end of the opening line: from index 3 a body starting `---\n---` would match
    # the opening line's own newline and pass the cap while the parser closes the block later.
    first_nl = text.find("\n") if text.startswith("---") else -1
    end = text.find("\n---", first_nl + 1) if first_nl != -1 else -1
    if text.startswith("---") and (end == -1 or end > _MAX_FRONTMATTER_CHARS):
        fm, body = {}, text
    else:
        try:
            fm, body = parse_frontmatter(text)
        except FrontmatterError:
            fm, body = {}, text  # tolerate a note written without frontmatter
    name = md.stem
    # Strings only, and checked before any str(): a YAML alias bomb or a huge int would
    # otherwise cost the whole session its context, not this one note its title.
    title, kind, tags = fm.get("title"), fm.get("type"), fm.get("tags")
    return Note(
        name=name,
        title=title if title and isinstance(title, str) else name,
        type=kind if kind and isinstance(kind, str) else "note",
        tags=tuple(_string_tags(tags)),
        body=body,
        links=tuple(parse_links(body)),
        path=md,
    )


def load_vault(repo: Path | str) -> Vault:
    """Load the vault's notes into a graph (empty if the vault is absent, or resolves outside the
    repo without the operator's say).

    Every folder below the vault is read, as Obsidian does, and a note's name is its file stem
    wherever it sits, so ``[[a-decision]]`` resolves to ``decisions/a-decision.md``. What the walk
    skips and where it stops is :func:`_walk`'s. Two files of one name (case aside): the one nearer
    the vault root is the note, then the one with the lower path, and the other is in ``shadowed``.
    The root map is the first of :data:`ROOT_MAP_NAMES` found at the vault root itself."""
    repo = Path(repo)
    vpath = vault_path(repo)
    notes: dict[str, Note] = {}
    if not vpath.is_dir() or not _vault_allowed(repo):
        return Vault(repo=repo, notes=notes)
    walk = _walk(vpath)
    shadowed: list[Path] = []
    truncated = walk.truncated
    spent = 0

    def charged_text(md: Path) -> str | None:
        """``md``'s text, its size charged to the budget before it is read, whether or not it
        then decodes or parses. None once the budget is spent (``truncated``)."""
        nonlocal spent, truncated
        size = _note_size(md, vpath)
        if size is None:
            return None
        if spent + size > _MAX_VAULT_BYTES:
            spent, truncated = _MAX_VAULT_BYTES, True  # spent: nothing after this one is read
            return None
        spent += size
        return _note_text(md)

    for md in walk.files:
        if md.stem.lower() in notes:
            shadowed.append(md)
            continue
        if spent >= _MAX_VAULT_BYTES:
            truncated = True
            break
        text = charged_text(md)
        if text is not None:
            notes[md.stem.lower()] = _parse_note(md, text)
    root = next(
        (
            key
            for key in (name.lower() for name in _WRITABLE_ROOT_MAPS)
            if key in notes and notes[key].path.parent == vpath
        ),
        None,
    )
    if root is None and walk.readme is not None:
        text = charged_text(walk.readme)
        if text is not None:
            root = walk.readme.stem.lower()
            notes[root] = _parse_note(walk.readme, text)
    return Vault(repo=repo, notes=notes, root=root, shadowed=tuple(shadowed), truncated=truncated)


def _link_key(target: str) -> str:
    """The note a wikilink target names. Obsidian also writes ``[[folder/name]]`` (to tell two
    notes of one name apart, or under its path link formats) and accepts ``[[name.md]]``: both
    resolve here by the last part, since a note's name is its stem."""
    key = target.replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
    return key[: -len(".md")] if key.endswith(".md") else key


def _inbound_counts(vault: Vault) -> dict[str, int]:
    counts = {name: 0 for name in vault.notes}
    for note in vault.notes.values():
        for target in note.links:
            key = _link_key(target)
            if key in counts and key != note.name.lower():  # a self-link must not mask an orphan
                counts[key] += 1
    return counts


def validate_vault(repo: Path | str) -> list[str]:
    """Return vault problems (empty = healthy): missing vault/root map, notes of one name in two
    folders, a walk that stopped at a cap, broken links, orphans."""
    repo = Path(repo)
    problems: list[str] = []
    vpath = vault_path(repo)
    if not vpath.is_dir():
        return [f"vault not found at {VAULT_DIRNAME}/"]
    if not _vault_allowed(repo):
        return [f"{VAULT_DIRNAME}/ not read: {_OUTSIDE}"]
    vault = load_vault(repo)
    if vault.root is None:
        names = ", ".join(f"{name}.md" for name in ROOT_MAP_NAMES)
        problems.append(f"missing root MOC (one of {names} at the vault root)")
    for path in sorted(vault.shadowed, key=lambda p: p.relative_to(vpath).as_posix()):
        kept = vault.notes[path.stem.lower()].path.relative_to(vpath).as_posix()
        problems.append(
            f"{path.stem}: duplicate note name, {path.relative_to(vpath).as_posix()} is not read "
            f"because {kept} is"
        )
    if vault.truncated:
        # A link to a note past the cap would read as broken, and a note only that one links to
        # as an orphan: neither check means anything on part of a vault, so neither is run.
        problems.append(
            f"the vault is larger than one load reads ({_MAX_NOTES} notes, {_MAX_DEPTH} folders "
            f"deep, {_MAX_WALK_ENTRIES} entries, {_MAX_VAULT_BYTES // (1024 * 1024)} MiB of "
            "notes): notes past that are not read, so links and orphans were not checked"
        )
        return problems
    # The root README is a meta-document, not a note, once another map exists; a link to it (an
    # Obsidian "Up: [[README]]" back-link, common in a vault that README used to map) still names
    # a file that is there, so it is not broken.
    meta = {"readme"} if _at_root(vpath, "README.md") is not None else set()
    for note in sorted(vault.notes.values(), key=lambda n: n.name):
        for target in note.links:
            if _link_key(target) not in vault.notes and _link_key(target) not in meta:
                problems.append(f"{note.name}: broken wikilink [[{target}]]")
    inbound = _inbound_counts(vault)
    for name, count in sorted(inbound.items()):
        if count == 0 and name != vault.root:
            problems.append(f"{vault.notes[name].name}: orphan (no note links to it)")
    return problems


def _render_note(title: str, body: str, *, type: str, tags: tuple[str, ...]) -> str:
    # Quoted, always: `a: b`, `*x`, `true`, `123` and `2026-01-01` are all something else plain,
    # and a JSON string is a YAML string. Non-ASCII stays readable in the file.
    quoted = json.dumps(title, ensure_ascii=False)
    tag_line = "[" + ", ".join(json.dumps(tag, ensure_ascii=False) for tag in tags) + "]"
    front = f"---\ntitle: {quoted}\ntype: {type}\ntags: {tag_line}\n---\n"
    return f"{front}\n# {title}\n\n{body.strip()}\n"


def _has_link(moc_path: Path, target: str) -> bool:
    existing = moc_path.read_text(encoding="utf-8")
    return f"[[{target}]]" in existing or f"[[{target}|" in existing


def _flat(vpath: Path, name: str) -> Path:
    """Where a new note ``name`` goes: the vault root. A name with a directory in it is refused
    before anything is written: a note is addressed by its name alone, and a link names no folder,
    so ``sub/x`` would be a note no one can tell from ``x``."""
    path = vpath / f"{name}.md"
    if path.parent != vpath:
        raise state_io.StateWriteRefused(errno.EINVAL, "a note name holds a directory", str(path))
    return path


def _at_root(vpath: Path, filename: str) -> Path | None:
    """The entry at the vault root named ``filename``, case aside (exact first), or None. A link
    counts, so that a writer finds it and refuses it rather than writing a second file beside it."""
    exact = vpath / filename
    if os.path.lexists(exact):
        return exact
    try:
        names = sorted(os.listdir(vpath))
    except OSError:
        return None
    want = filename.lower()
    return next((vpath / name for name in names if name.lower() == want), None)


def _root_map_path(vpath: Path) -> Path:
    """The root map a capture links from: the first of MOC, INDEX and Home at the vault root, else
    where scaffold writes ``MOC.md``. Never README.md, which nothing here writes once it exists."""
    for name in _WRITABLE_ROOT_MAPS:
        found = _at_root(vpath, f"{name}.md")
        if found is not None:
            return found
    return vpath / f"{ROOT_MOC}.md"


def _locate(vpath: Path, flat: Path, files: tuple[Path, ...]) -> Path:
    """Where the note at ``flat`` is now, resolved as :func:`load_vault` resolves it: the first of
    ``files`` (walk order: nearer the root, then the lower path, so ``X.md`` before ``x.md``) of its
    name, case aside, that a reader can read. With none, a file of its name at the vault root, link
    or not, so that the caller refuses a link rather than writing a second file beside it; else the
    first unreadable one of its name, which the write then replaces; else ``flat``, a new note."""
    stem = flat.stem.lower()
    named = [md for md in files if md.stem.lower() == stem]
    for md in named:
        if _note_size(md, vpath) is not None and _note_text(md) is not None:
            return md
    found = _at_root(vpath, flat.name)
    if found is not None:
        return found
    return named[0] if named else flat


def note_path(repo: Path | str, name: str) -> Path:
    """The file :func:`add_note` writes for ``name``: the one holding that note now, in whatever
    folder of the vault, else a new one at the vault root."""
    vpath = vault_path(repo)
    flat = _flat(vpath, name)
    if not vpath.is_dir() or not _vault_allowed(repo):
        return flat
    return _locate(vpath, flat, _walk(vpath).files)


def _refuse_target(path: Path, vpath: Path, *, links_to: str | None = None) -> None:
    """Raise :class:`state_io.StateWriteRefused` unless ``add_note`` can write at ``path``. With
    ``links_to``, ``path`` is a MOC that only has to hold that link, so one already holding it will
    not be written, and being read-only costs nothing. The read-only case is here because a replace
    needs only the directory: it would overwrite the file without a word, where a plain write
    raises. ``path`` may be in a folder of the vault: no link below the vault is crossed to it."""
    state_io.refuse_unsafe(path, vpath)
    if not path.exists():
        return
    if links_to is not None:
        try:
            if _has_link(path, links_to):
                return
        except UnicodeDecodeError:
            raise state_io.StateWriteRefused(errno.EINVAL, "not UTF-8 text", str(path)) from None
    if not os.access(path, os.W_OK):
        raise state_io.StateWriteRefused(errno.EACCES, "the file is read-only", str(path))


# The root map names, as a note or themed MOC name, on a filesystem that folds case too: a note
# called "index" would otherwise replace a vault's INDEX.md map.
_RESERVED_NAMES = tuple(name.lower() for name in ROOT_MAP_NAMES)
_FRONT = re.compile(r"---[ \t]*\r?\n(.*?)\r?\n---", re.DOTALL)
_TYPE_MOC = re.compile(r"(?m)^type:[ \t]*[\"']?moc[\"']?[ \t]*(?:#.*)?$")


def _is_moc(path: Path) -> bool:
    """True if the file's frontmatter says ``type: moc``. Read without PyYAML, which this write
    path otherwise does not need."""
    try:
        front = _FRONT.match(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return False
    return bool(front and _TYPE_MOC.search(front.group(1)))


def _refuse_outside(repo: Path | str) -> None:
    if not _vault_allowed(repo):
        raise state_io.StateWriteRefused(errno.EPERM, _OUTSIDE, str(vault_path(repo)))


def scaffold(repo: Path | str) -> Path:
    """Create the vault dir + root MOC + README if absent (idempotent). Return the vault path.

    Raises :class:`state_io.StateWriteRefused`, before creating anything, for a vault directory that
    resolves outside the repo without the operator's say, or for a dangling link or anything but a
    regular file at a name it would write. One that exists is not written, so it is not checked: a
    linked README stops nothing (ADR 0102).

    A vault whose root map was its README.md (no MOC, INDEX or Home) gets a ``MOC.md`` that starts
    with every wikilink the README holds. The new MOC is the root map from then on, and README.md
    goes back to being the vault's meta-doc, which is never written: so every note the README made
    reachable stays reachable, and the vault validates as it did before."""
    vpath = vault_path(repo)
    _refuse_outside(repo)
    moc = _root_map_path(vpath)  # a vault whose map is INDEX.md or Home.md gets no MOC.md
    readme = _at_root(vpath, "README.md") or vpath / "README.md"
    for path in (moc, readme):
        if not path.is_file():
            state_io.refuse_unsafe(path, vpath)
    vpath.mkdir(parents=True, exist_ok=True)
    if not moc.is_file():
        taken_over = _read_note(readme, vpath) if readme.is_file() else None
        links = [
            target
            for target in (taken_over.links if taken_over else ())
            if _link_key(target) not in (moc.stem.lower(), "readme")
        ]
        state_io.write_text(
            moc,
            _render_note(
                "Knowledge Map",
                "The map-of-content for this project's knowledge vault. Link notes here under "
                "themes.\n\n## Notes\n" + "".join(f"- {wikilink(t)}\n" for t in links),
                type="moc",
                tags=("moc",),
            ),
            anchor=vpath,
        )
    if not readme.is_file():
        state_io.write_text(
            readme,
            "# Knowledge vault\n\n"
            "Obsidian-format project knowledge maintained by agentic-forge's `knowledge` skill: "
            "atomic notes (`*.md` with `[[wikilinks]]`), maps-of-content (`type: moc`), entry "
            f"point `{moc.name}`.\n",
            anchor=vpath,
        )
    return vpath


def _ensure_moc(moc_path: Path, vpath: Path) -> Path:
    """Return ``moc_path``, creating it as a ``type: moc`` note if it doesn't exist yet."""
    if not moc_path.is_file():
        title = moc_path.stem.replace("-", " ").title()
        state_io.write_text(
            moc_path, _render_note(title, "## Notes\n", type="moc", tags=("moc",)), anchor=vpath
        )
    return moc_path


def _append_link(moc_path: Path, target: str, alias: str | None, vpath: Path) -> None:
    """Append ``- [[target|alias]]`` to a MOC file, unless ``target`` is already linked there."""
    if _has_link(moc_path, target):
        return
    existing = moc_path.read_text(encoding="utf-8")
    sep = "" if existing.endswith("\n") else "\n"
    text = f"{existing}{sep}- {wikilink(target, alias)}\n"
    state_io.write_text(moc_path, text, anchor=vpath)


def add_note(
    repo: Path | str,
    name: str,
    title: str,
    body: str,
    *,
    tags: tuple[str, ...] = (),
    type: str = "note",
    moc: str | None = ROOT_MOC,
) -> Path:
    """Write an atomic note and link it from ``moc`` (default the root map). Scaffolds if needed.

    **Upsert:** an existing note of the same ``name`` is overwritten (frontmatter, tags, and any
    hand edits included) — guard the caller if preserving existing content matters. It is
    overwritten where it is, in whatever folder of the vault (:func:`note_path`); a new note is
    written at the vault root, since a link names no folder. A ``moc`` is found the same way. The
    root map is the vault's own (MOC, INDEX or Home at the root), else ``MOC.md``, scaffolded.

    A themed (non-root) ``moc`` is created on demand **and linked from the root MOC**, so it is
    reachable (never an orphan) and the vault stays valid.

    A symlink at the note or at a MOC it would link from is refused, and so is anything else there
    that is not a regular file, or a file it would have to change that is read-only (ADR 0102). That
    raises
    :class:`state_io.StateWriteRefused`, an ``OSError`` naming the path, before anything is written.
    The caller is a skill someone is watching, so this is meant to be seen: the note was NOT saved.
    A root map name (``moc``, ``index``, ``home``, ``readme``) in any case is refused, as a note or
    a themed MOC, unless it is the root MOC itself: they are the vault's own files. So is replacing
    a ``type: moc`` file with a note, which would take its links with it (ADR 0104).
    A vault directory that resolves outside the repo is refused the same way, and the message gives
    the remedy; one that resolves inside it, through a link or not, works. The repo is the nearest
    directory up from ``repo`` holding a ``.git`` entry, so this works from a package directory.
    """
    _refuse_outside(repo)
    vpath = vault_path(repo)
    flat = vpath / f"{name}.md"
    if name.lower() in _RESERVED_NAMES or (
        moc and moc != ROOT_MOC and moc.lower() in _RESERVED_NAMES
    ):
        raise state_io.StateWriteRefused(errno.EINVAL, "a reserved vault name", str(flat))
    # Before scaffold, so that "before anything is written" holds on a fresh vault too.
    flat = _flat(vpath, name)
    themed = _flat(vpath, moc) if moc and moc != ROOT_MOC else None
    files = _walk(vpath).files if vpath.is_dir() else ()
    note_path = _locate(vpath, flat, files)
    _refuse_target(note_path, vpath)
    if type != "moc" and note_path.is_file() and _is_moc(note_path):
        raise state_io.StateWriteRefused(
            errno.EINVAL, "that name is a map-of-content", str(note_path)
        )
    root_path = _root_map_path(vpath)
    moc_path = _locate(vpath, themed, files) if themed is not None else root_path
    if moc:
        _refuse_target(moc_path, vpath, links_to=name)
        if themed is not None:
            _refuse_target(root_path, vpath, links_to=moc)
    scaffold(repo)
    state_io.write_text(note_path, _render_note(title, body, type=type, tags=tags), anchor=vpath)
    if moc:
        _ensure_moc(moc_path, vpath)
        if themed is not None:
            # a themed MOC must itself be reachable from the root, or validate flags it orphan
            _append_link(_ensure_moc(root_path, vpath), moc, None, vpath)
        _append_link(moc_path, name, title, vpath)
    return note_path


def recall_notes(repo: Path | str, query: str, *, limit: int = 5) -> list[tuple[Note, float]]:
    """Rank notes by deterministic overlap with ``query`` (title/tags weighted). Top ``limit``.

    Candidate retrieval only — the skill reads the winners and does the semantic synthesis.
    """
    vault = load_vault(repo)
    q = _tokens(query)
    if not q:
        return []
    scored: list[tuple[Note, float]] = []
    for note in vault.notes.values():
        weighted = _tokens(note.title, " ".join(note.tags))
        body = _tokens(note.body)
        score = 3.0 * len(q & weighted) + 1.0 * len(q & body)
        if score > 0:
            scored.append((note, score))
    scored.sort(key=lambda pair: (-pair[1], pair[0].name))
    return scored[:limit]


def recall(repo: Path | str, query: str, *, limit: int = 5) -> list[tuple[str, float]]:
    """:func:`recall_notes` by name: ``(name, score)`` pairs."""
    return [(note.name, score) for note, score in recall_notes(repo, query, limit=limit)]


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _shown(text: str) -> str:
    """``text`` as one line for the session context: runs of whitespace, line breaks included,
    become one space, and what is still not printable (a control or bidi character) is dropped."""
    return "".join(ch for ch in " ".join(text.split()) if ch.isprintable())


def session_summary(repo: Path | str, *, max_notes: int = 8) -> str:
    """A compact map to inject at session start: the root map + the highest-degree notes.

    Returns "" when there is no vault (a no-op for the session-start hook).
    """
    if not vault_path(repo).is_dir():
        return ""
    vault = load_vault(repo)
    if not vault.notes:
        return ""
    lines = [f"# Project knowledge ({VAULT_DIRNAME}/)", ""]
    root = vault.notes.get(vault.root) if vault.root else None
    if root:
        title = _clip(_shown(root.title), _SUMMARY_TITLE_CHARS)
        lines += [f"Map: [[{_shown(root.name)}]] — {title}", ""]
    inbound = _inbound_counts(vault)
    ranked = sorted(
        (n for key, n in vault.notes.items() if key != vault.root),
        key=lambda n: (-inbound[n.name.lower()], n.name),
    )
    if ranked:
        lines.append("Key notes:")
        lines += [
            f"- [[{_shown(n.name)}]] — {_clip(_shown(n.title), _SUMMARY_TITLE_CHARS)}"
            for n in ranked[:max_notes]
        ]
    return "\n".join(lines).rstrip() + "\n"
