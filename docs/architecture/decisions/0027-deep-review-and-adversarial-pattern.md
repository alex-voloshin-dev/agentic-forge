# 0027 — `deep-review` skill and the adversarial fan-out review pattern

Status: Accepted

## Context

The plugin already reviews **code** changes: the `multi-aspect-review` pattern fans one
reviewer per aspect (correctness, security, integration, style) and powers the `develop`
review gate and the `code-review` phase. But several high-value review tasks are **not** a
code diff: auditing a doc set or a design/ADR for contradictions and gaps, reviewing a
sizeable mixed change, or getting a rigorous adversarial second opinion where a single pass
(especially the author's own) reliably misses things. Routing those to `code-review` is a
mismatch — its aspects and its "one diff" framing don't fit a doc or design audit — and a
single `reviewer` pass has low recall on a large or subtle target.

This decision was made implicitly when the capability shipped; this ADR records it.

## Decision

Add a dedicated **`deep-review`** skill plus an **`adversarial-review`** pattern reference,
sitting alongside the existing `multi-aspect-review` pattern:

- **`adversarial-review.md`** (`plugin/patterns/`) — the general high-fidelity review harness:
  **decompose into lenses → fan out one fresh, independent reviewer per lens → verify every
  finding against the source → dedupe/prioritize → synthesize one report**. It is the review
  analogue of the research fan-out→verify→synthesize harness. Reviewers are prompted
  **adversarially** ("assume problems exist; hunt them") and return structured findings
  (`severity`, `location`, `issue`, `evidence`, `suggested fix`) using the canonical
  [`handoff.md`](../../../plugin/patterns/handoff.md) shape.
- **`deep-review`** (`plugin/skills/`) — the on-listing skill that orchestrates that pattern.
  Its description scopes it to a **non-trivial** target (doc set, design/architecture, sizeable
  change/PR, or the whole tree) and explicitly hands a quick single-file diff lint back to the
  lighter `code-review` skill. It picks target-appropriate lenses from its
  `references/lenses.md`, runs reviewers concurrently (Task fan-out, or a Workflow when the
  user opts into multi-agent orchestration), and optionally applies fixes and re-runs the gate.

The **verify** step is non-negotiable: every substantive finding is confirmed against the
source before it reaches the report, with notable false alarms recorded. Recall comes from
adversarial fan-out; precision comes from verification.

## Alternatives considered

- **Extend `code-review` to cover docs/design:** rejected — it would blur a sharp,
  well-routed description (the router would have to disambiguate "lint this diff" from "audit
  this design"), and the code aspects don't map onto a doc audit. Two sharp skills route
  better than one broad one (router discipline, [ADR 0004](0004-skill-centric-router.md)).
- **One `reviewer` pass for everything:** rejected — low recall on large/subtle targets; the
  whole point is to resist single-pass (and author) blind spots.
- **Make `deep-review` a pattern only (no skill):** rejected — a pattern isn't auto-loadable;
  users describe "review this thoroughly / audit for gaps" and need a skill that triggers.
  The pattern is the reusable method; the skill is the entry point.
- **Skip verification to save tokens:** rejected — adversarial prompting raises recall *and*
  false positives; without verification the caller is flooded with guesses. The
  "claims must be checkable" discipline of [ADR 0020](0020-tier2-inspection-gradeable-assertions.md)
  applies to the reviewers' own output here.

## Consequences

- `plugin/patterns/` now holds two complementary review patterns: `multi-aspect-review`
  (code; the `develop`/`code-review` engine) and `adversarial-review` (any target; the
  `deep-review` engine). Both build on `fan-out-fan-in` and emit `handoff.md`-shaped findings.
- `deep-review` is an own-behaviour skill, so it carries its own evals: Tier-1 trigger (it
  must win "audit / deep review / second opinion" prompts without stealing `code-review`'s
  single-diff prompts) and Tier-2 quality (a verified, deduplicated, prioritized report).
- This repo's own doc audits — including the review pass that produced ADRs 0027/0028 — use
  `deep-review`, so the plugin dogfoods its own review capability.
