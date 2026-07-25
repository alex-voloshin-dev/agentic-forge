---
type: release
feature: agentic-forge-2026.7.5
status: final
version: 2026.7.5
date: 2026-07-25
changelog:
  - "Added: `architecture` and `plan` gain a mandatory bounded skeptic pass plus the external-reviewer lens (`--kind technical` / `--kind plan`), exiting on the shared `handoff.review_loop_decision` — `architecture`'s pass was previously optional with no exit criterion, `plan` had none at all (ADR 0060)"
  - "Added: `plan` proves its dependency graph with `planning.plan_batches` (raises on a duplicate id, an unknown dependency, or a cycle) instead of asserting a cycle-free order in prose — a deterministic check at the phase that writes the plan (ADR 0060)"
  - "Added: `research` gains a mandatory bounded skeptic pass, independent of its own synthesize-and-verify step, plus the external lens (`--kind research`) — it previously had no independent review at all (ADR 0061)"
  - "Added: `ux-design`'s existing two-lens adversarial pass gains the contract — both lenses plus the external one (`--kind ux`) aggregate to a single verdict exiting on `review_loop_decision`, so `escalate` surfaces gaps instead of handing off (ADR 0061)"
  - "Added: `marketing`'s claims pass gains the shared exit criterion with an honestly conditional gate — schema validation for a typed handoff, the evidence discipline for the untyped deliverables — plus the external lens (`--kind marketing`) and an Output section (ADR 0062)"
  - "Added: three new `external_review.KINDS` (`research`, `ux`, `marketing`); without them an unknown kind falls back to the code criteria, so the external reviewer would critique a UX spec or a research brief as if it were a diff. Invariant: one kind per review-criteria set, tested as an exact set with pairwise-distinct criteria (ADR 0061 / 0062)"
  - "Fixed: `product`'s ADR-0057 external-reviewer call was unreachable — the skill had no `Bash` in `allowed-tools`, the same class of defect ADR 0037 fixed by adding `Task`. `Bash` added to `product`, `architecture`, `plan`, `research`, and `ux-design`, whose `handoff` / `planning` / `external_review` calls were equally unreachable (ADR 0060 / 0061)"
  - "Fixed: `ux-design` names where its artifact goes (`ux-spec.md` under `docs/sdlc/<feature-slug>/`) — the only phase skill specifying frontmatter but not the path, while `patterns/handoff.md` and the Tier-3 checkpoints already assumed it (ADR 0061)"
  - "Changed: docs synced for the wider wiring — `configuration.md`, `architecture/extensions.md`, `architecture/spine.md`, `architecture/design-onboarding.md`, `architecture/product-marketing.md`, `roadmap.md`, the `dev/external_review.py` docstring, and the `adversarial-review` / `review-loop` patterns; `component.purpose` updated in five `evals.json` files"
breaking: []
---

# Release 2026.7.5

One **review contract** for every workflow that writes a reviewable deliverable. Cut from a review of
the SDLC phases against the `product` / `develop` reference shape, which found the contract applied
inconsistently across the fleet.

## Why

ADR 0057 made the external reviewer a default review lens but wired it into only two workflows, and
ADR 0037's earlier audit — which concluded the bounded loop "now reaches every workflow that writes a
reviewable artifact" — had in fact missed two writers. The state before this release:

| Workflow | Before |
| --- | --- |
| `develop`, `product` | full shape (loop + external lens) |
| `architecture` | pass was "(Optional) … for a non-trivial design" — no exit criterion, no external lens, unmentioned in its definition of done |
| `plan` | **no review step at all** |
| `research` | **no independent review at all** — its "Synthesize & verify" is the author's own |
| `ux-design`, `marketing` | a real adversarial pass (ADR 0037) but no exit criterion and no external lens |

A review whose outcome does not gate the handoff is advice, not a gate. The gap mattered most in the
early phases: a defect in a brief, a design, or a build order is cheapest to catch there and costliest
once `develop` materialises it across every dependency level.

## What changed

All seven now run the same shape — **draft → bounded review (internal roster + the external lens when
enabled) → `handoff.review_loop_decision` → `proceed` ships, `escalate` stops** — with `cap = 3` and
early exit on `approve`, so a clean artifact still converges in one round.

| Workflow | External lens | `gate_green` |
| --- | --- | --- |
| `research` | `--kind research` | brief validates |
| `product` | `--kind product` | PRD validates |
| `architecture` | `--kind technical` | schema + goal traceability |
| `plan` | `--kind plan` | schema **and** `plan_batches` resolves |
| `ux-design` | `--kind ux` | ux-spec validates |
| `develop` | `--kind code` | suite green + QA |
| `marketing` | `--kind marketing` | schema (typed) / evidence discipline (untyped) |

Decisions: [ADR 0060](../../architecture/decisions/0060-skeptic-loop-architecture-plan.md),
[0061](../../architecture/decisions/0061-skeptic-loop-research-ux.md),
[0062](../../architecture/decisions/0062-skeptic-loop-marketing.md). Curated entries live in
`CHANGELOG.md` under `[2026.7.5]`. No breaking changes.

## Limits, stated

- **`marketing`'s gate is conditional.** Its untyped deliverables (content, offer doc, audit report)
  have no schema, so there the gate is the evidence discipline itself and the loop reduces to
  exit-on-`approve` / `escalate`. Weaker than `develop`'s QA gate or `plan`'s `plan_batches` — and
  still stronger than the status quo, which had no escalate discipline at all. Inventing a schema for
  landing copy to manufacture determinism would be worse than naming the limit (ADR 0062).
- **These are skill-body instructions executed by the model** (ADR 0013), not a machine gate. What is
  deterministically tested is the glue: `KINDS`, `review_loop_decision`, `plan_batches`. No eval
  assertions were added — "a review pass ran" is process-grading the read-only grader cannot verify
  from the artifact (ADR 0037 §5 / ADR 0020).

## Verification

- Tier-0: `dev/validate.py` OK; `pytest` green (coverage 96.66%, gate ≥ 80%); `ruff` / `mypy` clean.
- Tier-3 dry-run clean on all five scenarios (spine, quality-gate, ops-incident, product-inception,
  market-brief).
- **Tier-1 untouched** — no skill `description` changed, so routing and the ~1% listing budget are
  unaffected and no cost-gated re-run was required.
- New test: `KINDS` asserted as an exact set with pairwise-distinct criteria, so a missing kind
  (silent code-criteria fallback) or a copy-pasted duplicate fails Tier-0.

## Tag

`v2026.7.5` (annotated) on the merged master commit `8950e3a`, created after the PR's rebase merge
per CONTRIBUTING's "Cutting a release". **Deviation from the usual order:** this artifact was written
*after* the tag rather than inside the release commit (as in 2026.7.1–2026.7.4) — it was missed
during the cut and landed in a follow-up docs PR. The tag was deliberately **not** moved: rewriting a
published ref is worse than the artifact trailing it by one commit.
