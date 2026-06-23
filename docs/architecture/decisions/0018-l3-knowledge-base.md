# 0018 — L3 knowledge base: Obsidian vault + recall/capture skill + session-start hook

Status: Accepted

## Context

CLAUDE.md's core principles require a knowledge base: "the plugin deploys and maintains an
Obsidian-format markdown vault in the target repo (`[[wikilinks]]` + maps-of-content), and reads
it to enrich context." The layer (L3) has three parts — the **vault**, a **recall/capture
skill**, and **session-start injection** — and was the last "Planned" layer before guardrails
(L4). We build all three now (the session-start injection is the plugin's first hook).

The vault is durable project knowledge that does **not** belong in code or git history: design
rationale, prior art, gotchas, decisions-behind-the-decisions, "how we think about X." It is
Obsidian-format so a human can browse/edit it in Obsidian and on GitHub, and so the structure
(atomic notes + `[[wikilinks]]` + maps-of-content) is both human- and machine-navigable.

## Decision

- **Vault location: `docs/knowledge/` in the target repo.** Docs-adjacent, visible, browsable in
  Obsidian and on GitHub; mirrors how this repo uses `docs/`.
- **Vault format.** Atomic **notes** (kebab-case `.md`, YAML frontmatter `title` / `tags` /
  `type: note` + body with `[[wikilinks]]`), **maps-of-content (MOCs)** (`type: moc` index notes
  that link related notes), and a **root MOC** (`docs/knowledge/MOC.md`) as the entry point. A
  `[[name]]` (or `[[name|alias]]`) wikilink resolves to `name.md`.
- **Deterministic core in `lib/agentic_forge/vault.py`; semantic recall in the skill.** The lib
  does what must be exact and tested — parse/resolve wikilinks, load the note graph, **validate**
  (broken links, orphans, missing root MOC), **scaffold/deploy** an empty vault, **add+link** a
  note, and **rank candidate** notes for a query by deterministic token/tag/title overlap. The
  *semantic* judgement ("which of these candidates actually matter, synthesize them") is the
  skill's job, exactly as detection (deterministic) vs application (LLM) is split in by-stack.
- **A `knowledge` skill** (on-listing, with Tier-1 triggers + a Tier-2 contract): **recall** —
  detect the vault, rank candidates via `vault.recall`, read + synthesise the relevant notes to
  enrich the current task; **capture** — write a new *atomic* note via `vault.add_note`, wikilink
  it, and update the relevant MOC. It owns vault hygiene (atomic, linked, no orphans).
- **Session-start injection via a hook** (`plugin/hooks/`): the plugin's first hook. A
  `SessionStart` hook runs `plugin/hooks/scripts/session_start.py`, which reads the target repo's
  vault (if present) and injects a compact map — the root MOC plus the highest-degree notes — so
  a session starts already aware of what the project knows. Deterministic and unit-tested; a
  no-op when there is no vault. The hook logic reuses `vault.py` (shared, tested code), per the
  Python-only-tested-scripts rule.

## Alternatives considered

- **Vault at `.knowledge/` or top-level `knowledge/`:** rejected — `docs/knowledge/` is
  discoverable, docs-adjacent, and conventional; a hidden dir hurts browsability and a top-level
  dir competes with repos' own layout.
- **A bespoke (non-Obsidian) note format:** rejected — Obsidian wikilinks + MOCs are a de-facto
  standard, human-editable, and tool-supported; CLAUDE.md mandates it.
- **Pure-LLM recall (no deterministic lib):** rejected — broken-link/orphan validation and
  candidate retrieval must be exact and testable; an LLM-only recall can't be gated. (We still
  use the LLM for the semantic last mile, in the skill.)
- **Session-start injection as a skill, not a hook:** rejected — injection must happen
  automatically at session start regardless of routing; that is precisely a hook's job. (It does
  overlap L4 hook infra; building it here establishes the `plugin/hooks/` pattern L4 will reuse.)
- **Embeddings / vector search for recall:** rejected for now — adds a heavy dependency; token/
  tag/title overlap over an atomic-note vault is enough for candidate retrieval, and the LLM
  refines. Revisit if recall precision proves insufficient.

## Consequences

- New `lib/agentic_forge/vault.py` (tested ≥ 80%, aim 100%); a `knowledge` skill (Tier-0 +
  Tier-1, and Tier-2 via `run_skill_evals.py`); the first hook under `plugin/hooks/`
  (`hooks.json` + `scripts/session_start.py` + tests) — establishing the hook pattern for L4.
- The always-on router listing grows by one (`knowledge`); its triggers are seeded against the
  neighbours so Tier-1 specificity stays ≥ 0.9.
- The vault lives in the **target** repo, so the plugin's own `docs/knowledge/` (if any) is just
  dogfooding; the lib/skill/hook operate on whatever repo they run in.
- L3 moves from Planned to Built; only L4 (guardrails/observability) remains.

## Exit criteria

- `vault.py`: parse/resolve links, load graph, validate (broken/orphan/root-MOC), scaffold,
  add+link, recall — unit-tested, Tier-0 green, coverage ≥ 80%.
- `knowledge` skill: Tier-0 + Tier-1 (recall/specificity ≥ 0.9 on the live listing) green; a
  Tier-2 contract that `run_skill_evals.py` can run.
- Session-start hook: `hooks.json` valid, the script unit-tested (injects a vault map; no-op
  without a vault), wired so the plugin loads it.
- Docs (this ADR, `docs/architecture/knowledge.md`, overview/roadmap/meta-core/CHANGELOG)
  updated; independent adversarial review clean.
