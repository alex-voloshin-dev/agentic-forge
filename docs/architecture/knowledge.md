# Layer 3 — Knowledge base

Status: **Built** ([ADR 0018](decisions/0018-l3-knowledge-base.md)). The plugin deploys and
maintains an Obsidian-format knowledge vault in the target repo, reads it to enrich context via a
recall/capture skill, and injects its map at session start through the plugin's first hook.

The vault is durable project knowledge that does **not** belong in code or git history: the *why*
behind a decision, prior art, gotchas, "how we think about X." Obsidian-format so a human can
browse and edit it in Obsidian and on GitHub.

## The vault

Lives at `docs/knowledge/` in the target repo:

- **Notes** — atomic, one idea each; kebab-case `.md` with YAML frontmatter (`title` / `type:
  note` / `tags`) and a body using `[[wikilinks]]`.
- **Maps-of-content (MOCs)** — `type: moc` index notes that link related notes by theme.
- **Root map** — the entry point: `MOC.md` (what `scaffold` writes), else `INDEX.md`, `Home.md`
  or `README.md`, in that order, at the vault root itself and in any case. `README.md` is
  otherwise the vault's meta-doc, not a note, so it is the map only when none of the others is
  there, and nothing writes to it: a capture into such a vault scaffolds `MOC.md`, which then is
  the map. `index` and `home`, like `moc` and `readme`, are refused as a captured note's name.
- **Folders** — notes may sit in folders, at any depth, as in Obsidian (`decisions/`,
  `learnings/`, ...). A note's name is its file stem wherever it sits, so `[[name]]` /
  `[[name|alias]]` resolves to `name.md` in any folder (case-insensitively); `[[folder/name]]` and
  `[[name.md]]`, which Obsidian also writes, resolve by the last part.

### How the vault is read

`load_vault` walks the vault breadth first, each folder's entries in name order. It skips any
entry whose name starts with `.` (`.obsidian`, `.git`, `.trash`), any folder whose name starts
with `_` (Obsidian's convention for `_templates`, `_attachments`: a template's placeholders and
links are not knowledge), every `README.md` in a folder, and every symlink, file or folder. A link
is never followed, so the walk cannot leave the vault, loop, or read a note twice; a linked file
in the vault was already skipped before folders were read (ADR 0102).

The vault is read on every session start in a repo nobody vetted, so the walk is bounded. It
reads at most **5,000** notes, enters folders at most **8** deep, looks at most at **20,000**
directory entries of any kind, and reads at most **32 MiB** of note text (each note at most 2 MiB,
as before). Past a cap it keeps what it reached, shallowest first, and `validate_vault` reports
that the vault is larger than one load reads. Measured on generated vaults in 20 folders: 382
notes load in about 0.2 s, 2,000 in about 1 s with PyYAML installed (parsing frontmatter is most
of it; the walk itself is a few milliseconds) and 0.4 s without it, and 5,000, the cap, in about
2.6 s: inside the SessionStart hook's 15 s timeout, past which the hook would fail open.

**Two notes of one name** (case aside) in two folders: the one nearer the vault root is the note,
then the one whose path sorts lower, so a note at the root always wins and the result does not
depend on the filesystem's order. The other is not read, and `validate_vault` reports it as
`<name>: duplicate note name, <path> is not read because <path> is`. A file that cannot be read
does not shadow a readable one of its name.

**Capture** writes a new note at the vault root, since a link names no folder; an existing note of
that name is replaced where it is, in whatever folder, and a themed MOC is found the same way. The
root map it links from is the vault's own (MOC, INDEX or Home), else the scaffolded `MOC.md`.

## Deterministic core — `lib/agentic_forge/vault.py`

What must be exact and tested: parse/resolve wikilinks, load the note graph, **validate** (broken
links, orphans, missing root MOC), **scaffold** an empty vault, **add+link** an atomic note (and
create a themed MOC on demand), **rank recall candidates** by token/tag/title overlap, and build
the **session-start summary**. 100% line+branch. The *semantic* last mile — which candidates
matter, how to synthesise, what's worth capturing — is the skill's, exactly as detection
(deterministic) vs application (LLM) is split in by-stack.

## Recall + capture — the `knowledge` skill

On-listing (router) skill, reaching the library through `plugin/bin/af.py` (ADR 0104). **Recall:** detect the vault,
`vault-recall` for candidates, read the
top notes, answer grounded in them citing `[[links]]` (or say the vault is silent — never
invent). **Capture:** distill to atomic notes, `vault-add-note` (writes + links from a MOC; exits 1 rather than write through a linked file or into a vault
that resolves outside the repo, ADR 0102, and the skill reports that the note was not saved: it has no way of writing one by hand;
a new note's title and tags are quoted, and `moc` and `readme` are not note names, ADR 0104),
`vault-validate` and fix any broken link/orphan. It reads **our** notes — distinct from
`research` (the outside world). Gated by Tier-1 triggers and a Tier-2 capture-quality contract
(`run_skill_evals.py`).

## Session-start injection — the first hook

`plugin/hooks/hooks.json` registers a `SessionStart` command hook (auto-discovered at the plugin
root) running `hooks/scripts/session_start.py` via `${CLAUDE_PLUGIN_ROOT}`. The script reads the
payload's `cwd`, builds `vault.session_summary` (root MOC + highest-degree notes), and emits it as
SessionStart `additionalContext` so a session starts already aware of what the project knows. It
is a no-op without a vault and **never blocks the session** (any error exits 0). All logic lives
in the tested `vault.py`; the hook is thin glue. This establishes the `plugin/hooks/` pattern that
L4 (guardrails) will reuse.

## Eval model

- **Tier-0:** `validate.py`; `vault.py` and the hook are unit-tested (vault 100% line+branch).
- **`knowledge` skill:** Tier-1 (trigger recall/specificity ≥ 0.9 on the live listing) and a
  Tier-2 capture-quality contract run by `run_skill_evals.py`.
