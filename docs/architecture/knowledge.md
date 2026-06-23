# Layer 3 — Knowledge base (design + status)

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
- **Root MOC** — `MOC.md`, the entry point; a `[[name]]` / `[[name|alias]]` link resolves to
  `name.md` (case-insensitively).

## Deterministic core — `lib/agentic_forge/vault.py`

What must be exact and tested: parse/resolve wikilinks, load the note graph, **validate** (broken
links, orphans, missing root MOC), **scaffold** an empty vault, **add+link** an atomic note (and
create a themed MOC on demand), **rank recall candidates** by token/tag/title overlap, and build
the **session-start summary**. 100% line+branch. The *semantic* last mile — which candidates
matter, how to synthesise, what's worth capturing — is the skill's, exactly as detection
(deterministic) vs application (LLM) is split in by-stack.

## Recall + capture — the `knowledge` skill

On-listing (router) skill. **Recall:** detect the vault, `vault.recall` for candidates, read the
top notes, answer grounded in them citing `[[links]]` (or say the vault is silent — never
invent). **Capture:** distill to atomic notes, `vault.add_note` (writes + links from a MOC),
`vault.validate_vault` and fix any broken link/orphan. It reads **our** notes — distinct from
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
