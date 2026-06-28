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

import re
from dataclasses import dataclass
from pathlib import Path

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


def load_vault(repo: Path | str) -> Vault:
    """Load every ``.md`` note under the vault into a graph (empty if the vault is absent)."""
    repo = Path(repo)
    vpath = vault_path(repo)
    notes: dict[str, Note] = {}
    if not vpath.is_dir():
        return Vault(repo=repo, notes=notes)
    for md in sorted(vpath.glob("*.md")):
        if md.name == "README.md":
            continue  # vault meta-doc, not a knowledge note
        text = md.read_text(encoding="utf-8")
        try:
            fm, body = parse_frontmatter(text)
        except FrontmatterError:
            fm, body = {}, text  # tolerate a note written without frontmatter
        name = md.stem
        tags = fm.get("tags") or []
        note = Note(
            name=name,
            title=str(fm.get("title") or name),
            type=str(fm.get("type") or "note"),
            tags=tuple(str(t) for t in tags) if isinstance(tags, list) else (str(tags),),
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


def scaffold(repo: Path | str) -> Path:
    """Create the vault dir + root MOC + README if absent (idempotent). Return the vault path."""
    vpath = vault_path(repo)
    vpath.mkdir(parents=True, exist_ok=True)
    moc = vpath / f"{ROOT_MOC}.md"
    if not moc.is_file():
        moc.write_text(
            _render_note(
                "Knowledge Map",
                "The map-of-content for this project's knowledge vault. Link notes here under "
                "themes.\n\n## Notes\n",
                type="moc",
                tags=("moc",),
            ),
            encoding="utf-8",
        )
    readme = vpath / "README.md"
    if not readme.is_file():
        readme.write_text(
            "# Knowledge vault\n\n"
            "Obsidian-format project knowledge maintained by agentic-forge's `knowledge` skill: "
            "atomic notes (`*.md` with `[[wikilinks]]`), maps-of-content (`type: moc`), entry "
            f"point `{ROOT_MOC}.md`.\n",
            encoding="utf-8",
        )
    return vpath


def _ensure_moc(vpath: Path, moc: str) -> Path:
    """Return the MOC file path, creating it as a ``type: moc`` note if it doesn't exist yet."""
    moc_path = vpath / f"{moc}.md"
    if not moc_path.is_file():
        moc_path.write_text(
            _render_note(moc.replace("-", " ").title(), "## Notes\n", type="moc", tags=("moc",)),
            encoding="utf-8",
        )
    return moc_path


def _append_link(moc_path: Path, target: str, alias: str | None) -> None:
    """Append ``- [[target|alias]]`` to a MOC file, unless ``target`` is already linked there."""
    existing = moc_path.read_text(encoding="utf-8")
    if f"[[{target}]]" in existing or f"[[{target}|" in existing:
        return
    sep = "" if existing.endswith("\n") else "\n"
    moc_path.write_text(f"{existing}{sep}- {wikilink(target, alias)}\n", encoding="utf-8")


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
    """
    scaffold(repo)
    vpath = vault_path(repo)
    note_path = vpath / f"{name}.md"
    note_path.write_text(_render_note(title, body, type=type, tags=tags), encoding="utf-8")
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
