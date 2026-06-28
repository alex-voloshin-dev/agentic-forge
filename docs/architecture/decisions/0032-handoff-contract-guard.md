# 0032 — Handoff-contract guard: skill bodies must document their artifact's required fields

Status: Accepted — **implemented** (`skill_contract.py` + guard test; surfaced + fixed 5 skill-body gaps).

## Context

The live Tier-3 sweep showed a recurring failure: a skill produces a handoff artifact whose YAML
frontmatter is **missing a required field**, so `handoff.load_artifact` rejects it. The proven case
was `ux-design`, whose `SKILL.md` body listed the `ux-spec` domain fields (`flows`, `screens`, …)
but **not** the schema-required `feature` / `status` — so the model, anchored to the body, omitted
them. The per-phase retry (ADR 0030 runner) masks this; the root cause is **skill-body ↔ schema
drift**, and nothing catches it deterministically. See [quality-hardening.md](../quality-hardening.md).

## Decision

Add a deterministic guard that every artifact-producing skill's `SKILL.md` documents the fields its
handoff schema requires.

- A `SKILL_HANDOFF` mapping (skill name → handoff `type`) lives in `lib/` next to `handoff.py`.
- `handoff_contract_problems(plugin_dir)` returns, for each mapped skill, any **required field of
  its handoff schema** (derived from `handoff.SCHEMAS[type]`) that the skill body does **not**
  mention, plus a missing valid-frontmatter cue. Empty list = clean.
- A **pytest guard** asserts the live plugin is clean; unit tests cover a synthetic skill missing a
  field (flagged) and a complete one (clean). The gaps it surfaces are fixed in the skill bodies.

## Alternatives considered

- **Rely on the per-phase retry only:** rejected — retry masks the symptom and costs an extra model
  run each time; the guard fixes the cause and prevents regressions.
- **Declare the handoff type in skill frontmatter** (a new optional field) instead of a `lib/`
  mapping: rejected for now — it adds a non-standard frontmatter field to every skill; a small
  central mapping is less invasive and equally testable. (Can revisit if skills proliferate.)
- **Wire the check into `dev/validate.py` (hard Tier-0):** kept as an option, but a pytest guard is
  enough to block in CI and keeps `validate.py` focused on standard-compliance; the check lives in
  `lib/` so it can be promoted to `validate.py` later without moving logic.
- **Substring matching is imperfect** (a body could mention a field name in passing): accepted — a
  presence check catches the real drift (a wholly-absent required field) cheaply; it is a floor, not
  a proof of correct usage (that is what the eval tiers are for).

## Consequences

- Skill bodies and their handoff schemas can't silently drift apart; the `ux-design`-class gap is
  caught at Tier-0 (pytest), not only at a live run.
- A new `SKILL_HANDOFF` mapping must be kept in step when a new artifact-producing skill is added —
  itself enforced by the guard (an unmapped artifact skill is a deliberate, reviewable omission).
- Live chains rely **less** on retry, because phases emit schema-valid artifacts more reliably.
