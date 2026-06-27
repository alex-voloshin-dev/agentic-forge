# 0030 — Domain E2E: extend Tier-3 to Stage 4–6 via deterministic chain scenarios

Status: Accepted (design; implementation pending)

## Context

Tier-3 (end-to-end) covers only the SDLC spine ([spine.md](../spine.md),
`spine_e2e.py`): one feature carried through the six phases on an isolated fixture with
deterministic per-phase checkpoints. The Stage 4–6 domain skills — `qa-test-strategy`,
`security-review`, `deploy-watch`, `incident-response`, `release`, `marketing`, `ux-design`,
`repo-onboarding` — have Tier-1 (routing) and mostly Tier-2 (LLM-judged quality), but no Tier-3.

Tier-2 ≠ Tier-3: Tier-2 runs a *single* skill and grades its output with an LLM judge; Tier-3
drives a realistic scenario and validates **concrete outcomes deterministically**. Neither tier
tests the **handoffs between the new domains and the spine**. The full design is in
[domain-e2e.md](../domain-e2e.md); this ADR records the decisions.

## Decision

1. **Grow Tier-3 by domain *chains*, not per-skill repeats.** Add a small set of multi-skill
   scenarios that exercise the new domains together with the spine, each ending in validated
   artifacts/outcomes. A per-skill E2E for all eight would largely duplicate Tier-2.

2. **Generalize `spine_e2e.py` into a `Scenario` abstraction** (`Phase{skill, prompt, checks}`,
   `Scenario{name, fixture, slug, phases, seed}`, `run_scenario(...)`) and register the spine as
   one scenario. Reuse the `claude` runner seam, `prepare_workspace`, `Checkpoint`/`PhaseResult`,
   the dry-run wiring check, and the `handoff` / `vault` validators. The refactor is
   behaviour-preserving — `tests/test_spine_e2e.py` is the guard.

3. **Checkpoints stay deterministic** (no LLM judge in the gate): schema validation
   (`handoff.load_artifact`), computed outcomes (exact `release` semver bump; `incident` severity
   in `INCIDENT_SEVERITIES`; `deploy-watch` health vs canned data; `repo-onboarding` vault via
   `validate_vault`), and **planted defects** (a known SQL-injection sink for `security-review`,
   as in the `deep-review` fixture).

4. **Scope and order.** Wave 1: `quality-gate` (qa-test-strategy → develop → security-review →
   code-review → release) and `ops-incident` (deploy-watch → incident-response → release). Wave 2:
   `product-inception` (repo-onboarding → research → product → ux-design → architecture).
   **`marketing` is excluded** — its value is live web research (non-deterministic; already judged
   at Tier-2), so it keeps Tier-0 schema validation only.

5. **Cost-gated, on-demand.** Each phase is a full `claude` session; scenarios run only via
   `eval.yml` (dispatch / `eval` label), like the spine. The free `--runner dry` wiring check
   stays always-on.

## Alternatives considered

- **Per-skill E2E for all eight domains:** rejected — mostly duplicates Tier-2 (which already runs
  each skill on a fixture). Chains test what neither Tier-2 nor the spine does: the cross-domain
  handoffs.
- **One bespoke runner per scenario (no shared model):** rejected — `spine_e2e.py` is already
  data-driven; a `Scenario` registry is less code, keeps the spine and new scenarios on one tested
  path, and makes adding a scenario a data change.
- **LLM-judged checkpoints (reuse the Tier-2 grader):** rejected for the *gate* — Tier-3's value
  is deterministic outcome validation; judging would re-introduce Tier-2's variance and blur the
  tiers. (An LLM judge may still *inform* a fixture's planted defect, but the gate stays
  deterministic.)
- **Include `marketing`:** rejected — cited-competitor/source quality is inherently
  non-deterministic and best left to Tier-2 + the connector (WebSearch) path; a deterministic E2E
  would test little beyond schema, which Tier-0 already does.
- **Re-run the full spine inside `quality-gate`:** rejected — wasteful (~6 extra sessions); seed
  the existing spine artifact fixtures and start from the quality/ops tail.

## Consequences

- Tier-3 grows from one scenario to several; the spine refactors onto the shared `Scenario`
  model with no behaviour change.
- Five of the eight domains gain end-to-end coverage in wave 1 (qa-test-strategy, security-review,
  release, deploy-watch, incident-response); onboarding + ux follow in wave 2; `marketing` stays
  Tier-0/Tier-2 only, recorded here as a deliberate exclusion.
- New fixtures are needed: a `quality-gate` target repo (tagged baseline + a planted-defect
  variant) and a minimal `ops-incident` workspace; the rest are reused from Tier-2.
- The implementation must still follow contract → evals → implementation → gate, with a recorded
  live run and unit tests on stubbed phases (≥ 80% coverage), per [domain-e2e.md](../domain-e2e.md).
