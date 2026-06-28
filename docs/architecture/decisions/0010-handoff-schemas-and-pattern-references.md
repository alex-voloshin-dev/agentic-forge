# 0010 — Handoff header schemas and pattern-reference location

Status: Accepted (relaxed by [ADR 0028](0028-handoff-contract-relaxation.md))

## Context

Stage 1 implements the engine foundations designed in [ADR 0009](0009-engine-roles-and-handoff.md)
and [engine.md](../engine.md): the handoff helper plus the per-type header schemas, and the
pattern references (handoff, review loop, worktree) that Stage 2 skills will consume. Two
implementation choices needed pinning down: how strictly to type the handoff headers, and
where the pattern references live so they ship inside the plugin.

## Decision

- **Handoff headers are validated with per-type JSON Schemas** in
  `lib/agentic_forge/handoff.py`, reusing `frontmatter.py` to split the artifact and
  `jsonschema` (already a dependency) to validate the header — the same approach as
  `evals.py`. Each schema:
  - requires the identity fields a consumer needs (`type` pinned with `const`; `feature` +
    `status` for feature artifacts; `target` + `iteration` + `verdict` for reviews) and the
    primary domain lists (`goals`/`acceptance`, `decisions`/`components`, `tasks`);
  - type-checks the remaining list fields when present, but does not require them;
  - constrains small vocabularies that consumers branch on: `status`
    (`draft|in-review|approved|final|superseded`), `verdict` (`approve|changes`), finding
    `severity` (`blocker|major|minor|nit`);
  - sets `additionalProperties: true` so artifacts may carry extra fields without breaking.
- **Pattern references live in `plugin/patterns/`** as plain Markdown
  (`handoff.md`, `review-loop.md`, `worktree.md`), referenced by Stage 2 skills on demand.

## Alternatives considered

- **Hand-rolled header checks** (like `naming.py`): rejected — `jsonschema` is already used by
  `evals.py`, gives declarative schemas and consistent error messages, and keeps the
  validator logic small.
- **Require every listed key field:** rejected as too brittle — requiring the identity and
  primary fields guarantees a usable contract; over-requiring secondary lists would reject
  legitimately sparse artifacts. Type-checking optional fields still protects consumers.
- **Pattern references in `docs/`:** rejected — only `plugin/` ships when the plugin is
  installed, so runtime-consumable references must live under `plugin/`. `docs/` remains the
  home for design intent (engine.md) and ADRs.
- **Pattern references as `user-invocable: false` skills:** rejected — they would consume the
  router listing budget for content that is reference material, not a workflow. Progressive
  disclosure via plain Markdown links is the right mechanism.

## Consequences

- Downstream phases can trust handoff header fields they parse instead of re-deriving them
  from prose; malformed artifacts fail fast with located error messages.
- `plugin/patterns/` is a new plugin subdirectory. The Tier-0 validator walks only `skills/`
  and `agents/`, so the patterns are inert to validation (correct — they are reference docs)
  and ship with the plugin.
- The status/verdict/severity vocabularies are now part of the handoff contract; changing
  them is a breaking change for any consumer that branches on them.
