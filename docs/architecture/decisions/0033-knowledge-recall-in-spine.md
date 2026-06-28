# 0033 — Knowledge recall in the spine phases

Status: Accepted — **implemented** (6 spine phases + `patterns/knowledge-recall.md` + a presence guard).

## Context

`CLAUDE.md` says the plugin "deploys and maintains an Obsidian-format markdown vault … **and reads
it to enrich context**" — workflows should consume the vault, not only write it. Today the write/seed
side exists (`repo-onboarding` seeds the
vault; `knowledge` captures notes) and a session-start hook injects a vault summary — but the
**spine phases themselves do not recall** the relevant prior notes before acting. So a phase can
re-decide something the project already settled. See [quality-hardening.md](../quality-hardening.md),
[knowledge.md](../knowledge.md).

## Decision

Each spine phase recalls relevant vault context as an explicit process step before producing its
artifact.

- Add a **"Recall prior context"** step to the `research`, `product`, `architecture`, `plan`,
  `develop`, and `code-review` skill bodies: recall relevant notes from the vault
  (`docs/knowledge/`, via the `knowledge` skill / `vault.recall`), and factor prior decisions into
  the phase's output (cite the note when a decision leans on it).
- Capture the step once in a shared reference `patterns/knowledge-recall.md` (what to recall, when,
  how to cite, and "skip if the vault is absent"), referenced by each phase so the bodies stay lean.
- A **guard test** asserts each spine skill body references the recall step / the pattern (presence),
  so the integration can't silently regress.

## Alternatives considered

- **Session-start hook only (status quo):** rejected — a one-time summary at session start is not
  per-phase, targeted recall; the architecture phase should pull *architecture* decisions, not a
  generic digest.
- **A dedicated "recall" subagent each phase forks:** rejected as heavier than needed — the existing
  `vault.recall` ranking + the `knowledge` skill already do retrieval; the phase just needs to *use*
  them. A fork can be added later if recall needs its own tools.
- **Make recall mandatory / fail if no notes:** rejected — a fresh repo has an empty vault; recall
  must **degrade to a no-op** when the vault is absent or empty, never block the phase.
- **Bake recall into every domain skill too (not just the spine):** deferred — start with the spine
  (the proven chain); domain skills can adopt the same pattern reference incrementally.

## Consequences

- The spine becomes context-aware: phases build on recorded decisions instead of re-deriving them,
  realizing the constitution's read-the-vault intent.
- One shared `patterns/knowledge-recall.md` keeps the six bodies consistent and lean; the guard test
  keeps the step from being dropped.
- Recall quality isn't newly gated (it's exercised by the `knowledge` Tier-2 + the spine Tier-3);
  the guard only ensures the *step is present*. The step is a no-op on an empty vault, so it never
  destabilizes a greenfield run.
