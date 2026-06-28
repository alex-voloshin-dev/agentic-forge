# Pattern: knowledge recall (read the vault to enrich a phase)

Before a workflow phase produces its artifact, **recall the project's relevant prior decisions**
from the knowledge vault (`docs/knowledge/`) so it builds on what's already settled instead of
re-deriving it. This realizes the constitution's "workflows … read [the vault] to enrich their
context" ([ADR 0033](../../docs/architecture/decisions/0033-knowledge-recall-in-spine.md)).

## When

Every SDLC spine phase (`research → product → architecture → plan → develop → code-review`), at the
**start** (while reading inputs). Domain skills may adopt it too.

## How

1. **Recall.** Query the vault for notes relevant to the feature/topic — `vault.recall(repo, query)`
   (ranked) or the `knowledge` skill. Use the phase's subject as the query (the feature slug + the
   phase's concern, e.g. "auth", "rate limiting").
2. **Factor in.** Let recalled decisions shape the output; don't silently contradict a settled
   decision — call it out if you must diverge.
3. **Cite.** When a choice leans on a note, reference it (`[[note]]`) so the trail is auditable.
4. **Capture back (optional).** New durable decisions the phase makes are candidates for the
   `knowledge` skill to save.

## Degrade gracefully

If the vault is absent or empty (a greenfield repo), recall is a **no-op** — never block the phase.

## Composition

- Retrieval is `vault.recall` / the `knowledge` skill; the vault is seeded by `repo-onboarding`.
- Used by the spine phase skills; it emits nothing of its own — it enriches the phase's existing
  output and handoff artifact.
