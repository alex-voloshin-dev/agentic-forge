"""Obsidian-format knowledge vault for a target repo (ADR 0018).

The vault lives at ``<repo>/docs/knowledge/``: atomic **notes** (kebab-case ``.md``, YAML
frontmatter + a ``[[wikilink]]`` body), **maps-of-content** (``type: moc``), and a root MOC
(``MOC.md``) as the entry point. This module is the deterministic, tested core — parse/resolve
wikilinks, load the note graph, **validate** it (broken links, orphans, missing root MOC),
**scaffold** an empty vault, **add+link** a note, **rank recall candidates** for a query, and
build the **session-start summary**. The *semantic* last mile (which candidates matter, how to
synthesise) belongs to the ``knowledge`` skill.
"""

from __future__ import annotations

import errno
import os
import re
from dataclasses import dataclass
from pathlib import Path

from agentic_forge import settings, state_io
from agentic_forge.frontmatter import FrontmatterError
from agentic_forge.frontmatter import parse as parse_frontmatter

__all__ = [
    "VAULT_DIRNAME",
    "ROOT_MOC",
    "Note",
    "Vault",
    "vault_path",
    "wikilink",
    "parse_links",
    "load_vault",
    "validate_vault",
    "scaffold",
    "add_note",
    "recall",
    "session_summary",
    "outside_repo_notice",
]

VAULT_DIRNAME = "docs/knowledge"
ROOT_MOC = "MOC"  # the root map-of-content note, MOC.md

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


def load_vault(repo: Path | str) -> Vault:
    """Load every ``.md`` note under the vault into a graph (empty if the vault is absent, or
    resolves outside the repo without the operator's say). A note that cannot be read as UTF-8 is
    skipped: one file in a repo must not take the rest of a session's context with it."""
    repo = Path(repo)
    vpath = vault_path(repo)
    notes: dict[str, Note] = {}
    if not vpath.is_dir() or not _vault_allowed(repo):
        return Vault(repo=repo, notes=notes)
    for md in sorted(vpath.glob("*.md")):
        if md.name == "README.md":
            continue  # vault meta-doc, not a knowledge note
        if not state_io.readable(md, vpath):
            continue  # a linked file is another file: its frontmatter must not reach a session
        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            fm, body = parse_frontmatter(text)
        except FrontmatterError:
            fm, body = {}, text  # tolerate a note written without frontmatter
        name = md.stem
        # Strings only, and checked before any str(): a YAML alias bomb or a huge int would
        # otherwise cost the whole session its context, not this one note its title.
        title, kind, tags = fm.get("title"), fm.get("type"), fm.get("tags")
        note = Note(
            name=name,
            title=title if title and isinstance(title, str) else name,
            type=kind if kind and isinstance(kind, str) else "note",
            tags=tuple(_string_tags(tags)),
            body=body,
            links=tuple(parse_links(body)),
            path=md,
        )
        notes[name.lower()] = note
    return Vault(repo=repo, notes=notes)


def _inbound_counts(vault: Vault) -> dict[str, int]:
    counts = {name: 0 for name in vault.notes}
    for note in vault.notes.values():
        for target in note.links:
            key = target.lower()
            if key in counts and key != note.name.lower():  # a self-link must not mask an orphan
                counts[key] += 1
    return counts


def validate_vault(repo: Path | str) -> list[str]:
    """Return vault problems (empty = healthy): missing vault/root MOC, broken links, orphans."""
    repo = Path(repo)
    problems: list[str] = []
    if not vault_path(repo).is_dir():
        return [f"vault not found at {VAULT_DIRNAME}/"]
    if not _vault_allowed(repo):
        return [f"{VAULT_DIRNAME}/ not read: {_OUTSIDE}"]
    vault = load_vault(repo)
    if ROOT_MOC.lower() not in vault.notes:
        problems.append(f"missing root MOC ({ROOT_MOC}.md)")
    for note in sorted(vault.notes.values(), key=lambda n: n.name):
        for target in note.links:
            if target.lower() not in vault.notes:
                problems.append(f"{note.name}: broken wikilink [[{target}]]")
    inbound = _inbound_counts(vault)
    for name, count in sorted(inbound.items()):
        if count == 0 and name != ROOT_MOC.lower():
            problems.append(f"{vault.notes[name].name}: orphan (no note links to it)")
    return problems


def _render_note(title: str, body: str, *, type: str, tags: tuple[str, ...]) -> str:
    tag_line = "[" + ", ".join(tags) + "]"
    front = f"---\ntitle: {title}\ntype: {type}\ntags: {tag_line}\n---\n"
    return f"{front}\n# {title}\n\n{body.strip()}\n"


def _has_link(moc_path: Path, target: str) -> bool:
    existing = moc_path.read_text(encoding="utf-8")
    return f"[[{target}]]" in existing or f"[[{target}|" in existing


def _refuse_target(path: Path, vpath: Path, *, links_to: str | None = None) -> None:
    """Raise :class:`state_io.StateWriteRefused` unless ``add_note`` can write at ``path``. With
    ``links_to``, ``path`` is a MOC that only has to hold that link, so one already holding it will
    not be written, and being read-only costs nothing. The read-only case is here because a replace
    needs only the directory: it would overwrite the file without a word, where a plain write
    raises. A name with a directory in it is refused because the helper would create the directory,
    and the vault loads only its top level, so the note would be saved and never found."""
    state_io.refuse_unsafe(path, vpath)
    if path.parent != vpath:
        raise state_io.StateWriteRefused(errno.EINVAL, "a note name holds a directory", str(path))
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


def _refuse_outside(repo: Path | str) -> None:
    if not _vault_allowed(repo):
        raise state_io.StateWriteRefused(errno.EPERM, _OUTSIDE, str(vault_path(repo)))


def scaffold(repo: Path | str) -> Path:
    """Create the vault dir + root MOC + README if absent (idempotent). Return the vault path.

    Raises :class:`state_io.StateWriteRefused`, before creating anything, for a vault directory that
    resolves outside the repo without the operator's say, or for a dangling link or anything but a
    regular file at a name it would write. One that exists is not written, so it is not checked: a
    linked README stops nothing (ADR 0102)."""
    vpath = vault_path(repo)
    _refuse_outside(repo)
    moc = vpath / f"{ROOT_MOC}.md"
    readme = vpath / "README.md"
    for path in (moc, readme):
        if not path.is_file():
            state_io.refuse_unsafe(path, vpath)
    vpath.mkdir(parents=True, exist_ok=True)
    if not moc.is_file():
        state_io.write_text(
            moc,
            _render_note(
                "Knowledge Map",
                "The map-of-content for this project's knowledge vault. Link notes here under "
                "themes.\n\n## Notes\n",
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
            f"point `{ROOT_MOC}.md`.\n",
            anchor=vpath,
        )
    return vpath


def _ensure_moc(vpath: Path, moc: str) -> Path:
    """Return the MOC file path, creating it as a ``type: moc`` note if it doesn't exist yet."""
    moc_path = vpath / f"{moc}.md"
    if not moc_path.is_file():
        state_io.write_text(
            moc_path,
            _render_note(moc.replace("-", " ").title(), "## Notes\n", type="moc", tags=("moc",)),
            anchor=vpath,
        )
    return moc_path


def _append_link(moc_path: Path, target: str, alias: str | None) -> None:
    """Append ``- [[target|alias]]`` to a MOC file, unless ``target`` is already linked there."""
    if _has_link(moc_path, target):
        return
    existing = moc_path.read_text(encoding="utf-8")
    sep = "" if existing.endswith("\n") else "\n"
    text = f"{existing}{sep}- {wikilink(target, alias)}\n"
    state_io.write_text(moc_path, text, anchor=moc_path.parent)


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
    """Write an atomic note and link it from ``moc`` (default the root MOC). Scaffolds if needed.

    **Upsert:** an existing note of the same ``name`` is overwritten (frontmatter, tags, and any
    hand edits included) — guard the caller if preserving existing content matters.

    A themed (non-root) ``moc`` is created on demand **and linked from the root MOC**, so it is
    reachable (never an orphan) and the vault stays valid.

    A symlink at the note or at a MOC it would link from is refused, and so is anything else there
    that is not a regular file, or a file it would have to change that is read-only (ADR 0102). That
    raises
    :class:`state_io.StateWriteRefused`, an ``OSError`` naming the path, before anything is written.
    The caller is a skill someone is watching, so this is meant to be seen: the note was NOT saved.
    A vault directory that resolves outside the repo is refused the same way, and the message gives
    the remedy; one that resolves inside it, through a link or not, works. The repo is the nearest
    directory up from ``repo`` holding a ``.git`` entry, so this works from a package directory.
    """
    _refuse_outside(repo)
    vpath = vault_path(repo)
    note_path = vpath / f"{name}.md"
    # Before scaffold, so that "before anything is written" holds on a fresh vault too.
    _refuse_target(note_path, vpath)
    if moc:
        _refuse_target(vpath / f"{moc}.md", vpath, links_to=name)
        if moc != ROOT_MOC:
            _refuse_target(vpath / f"{ROOT_MOC}.md", vpath, links_to=moc)
    scaffold(repo)
    state_io.write_text(note_path, _render_note(title, body, type=type, tags=tags), anchor=vpath)
    if moc:
        moc_path = _ensure_moc(vpath, moc)
        if moc != ROOT_MOC:
            # a themed MOC must itself be reachable from the root, or validate flags it orphan
            _append_link(_ensure_moc(vpath, ROOT_MOC), moc, None)
        _append_link(moc_path, name, title)
    return note_path


def recall(repo: Path | str, query: str, *, limit: int = 5) -> list[tuple[str, float]]:
    """Rank notes by deterministic overlap with ``query`` (title/tags weighted). Top ``limit``.

    Candidate retrieval only — the skill reads the winners and does the semantic synthesis.
    """
    vault = load_vault(repo)
    q = _tokens(query)
    if not q:
        return []
    scored: list[tuple[str, float]] = []
    for note in vault.notes.values():
        weighted = _tokens(note.title, " ".join(note.tags))
        body = _tokens(note.body)
        score = 3.0 * len(q & weighted) + 1.0 * len(q & body)
        if score > 0:
            scored.append((note.name, score))
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return scored[:limit]


def session_summary(repo: Path | str, *, max_notes: int = 8) -> str:
    """A compact map to inject at session start: the root MOC body + the highest-degree notes.

    Returns "" when there is no vault (a no-op for the session-start hook).
    """
    if not vault_path(repo).is_dir():
        return ""
    vault = load_vault(repo)
    if not vault.notes:
        return ""
    lines = [f"# Project knowledge ({VAULT_DIRNAME}/)", ""]
    root = vault.notes.get(ROOT_MOC.lower())
    if root:
        lines += [f"Map: [[{root.name}]] — {root.title}", ""]
    inbound = _inbound_counts(vault)
    ranked = sorted(
        (n for n in vault.notes.values() if n.name.lower() != ROOT_MOC.lower()),
        key=lambda n: (-inbound[n.name.lower()], n.name),
    )
    if ranked:
        lines.append("Key notes:")
        lines += [f"- [[{n.name}]] — {n.title}" for n in ranked[:max_notes]]
    return "\n".join(lines).rstrip() + "\n"
