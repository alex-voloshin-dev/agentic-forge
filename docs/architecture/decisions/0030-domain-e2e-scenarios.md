# 0030 — Domain E2E: extend Tier-3 to Stage 4–6 via deterministic chain scenarios

Status: Accepted — **Wave 1 implemented** (`quality-gate` + `ops-incident`); Wave 2 pending.
Revised after a deep multi-reviewer review.

## Context

Tier-3 (end-to-end) covers only the SDLC spine ([spine.md](../spine.md), `spine_e2e.py`): one
feature carried through the six phases on an isolated fixture with deterministic per-phase
checkpoints. The Stage 4–6 domain skills — `qa-test-strategy`, `security-review`, `deploy-watch`,
`incident-response`, `release`, `marketing`, `ux-design`, `repo-onboarding` — have Tier-1
(routing) and most have Tier-2 (LLM-judged quality), but no Tier-3.

What Tier-3 uniquely adds over the lower tiers: (a) the **cross-domain handoffs** (no tier tests
them — Tier-1/2 are single-skill), and (b) **deterministic outcome checks** (a computed semver
bump, an enum severity, a clean vault, a found planted defect) that Tier-2's LLM judge does not
make. The full design is in [domain-e2e.md](../domain-e2e.md); this ADR records the decisions.

## Decision

1. **Grow Tier-3 by domain *chains* + a few deterministic single-skill complements, not per-skill
   repeats.** The justification is the **handoff**: the cross-domain handoffs are untested by any
   tier, and a chain end-to-end proves a skill actually *consumes* the prior artifact. (A
   secondary reason — per-skill repeats would duplicate Tier-2 — holds only for the **six** domains
   that have a fixture-backed Tier-2; the two fork-orchestrators `qa-test-strategy` /
   `security-review` are **Tier-1-only** by [ADR 0021](0021-stage4-ops-seam-and-eval-tiers.md), so
   their end-to-end behaviour is genuinely uncovered and a chain is the only gate.)

2. **Generalize `spine_e2e.py` into a `Scenario` abstraction** (`Phase{skill,prompt,checks}`,
   `Scenario{name,fixture,slug,phases,seed}`, `run_scenario(...)`), registering the spine as one
   scenario. This is a **real refactor, not a rename**: `FEATURE_SLUG`/`FIXTURE_REPO`/`PHASES` are
   module constants and the `check_*`/`_phase_prompt` helpers close over `FEATURE_SLUG`, so `slug`/
   `fixture` must be threaded through and `seed` extended to arbitrary destination paths. The
   refactor is behaviour-preserving for the spine (`tests/test_spine_e2e.py` is the guard); the
   **new `seed`/multi-scenario plumbing gets its own stubbed-phase tests** (the spine test does not
   exercise it).

3. **Checkpoints use no LLM judge in the gate.** Each is (D) a code comparison
   (`release.summarize(...).version`; `ops.classify_incident(...)`; `ops.rollout_health(...)`;
   `vault.validate_vault`; the repo `pytest` run), (D-sub) a substring/location match on the
   model's artifact (a planted sink's path/symbol in `findings[].location`; named competitors in
   the `market-brief`), or (carrier) schema-only validation of a handoff gated elsewhere. Two
   checkpoints that an earlier draft called "deterministic" actually need care: "finds the planted
   issue" is made deterministic as a **location substring** match (not the LLM-judged form
   `deep-review` uses); "names ≥1 real risk area" becomes `test_levels` non-empty + a known-risk
   **keyword** assertion (the `test-strategy` schema does not enforce `risks` non-empty).

4. **Scope — all eight domains covered.** Wave 1: `quality-gate` (qa-test-strategy → develop →
   security-review → code-review → release) and `ops-incident` (deploy-watch → incident-response →
   release). Wave 2: `product-inception` (repo-onboarding → research → product → ux-design →
   architecture, with the spine phases as **carriers** for the handoffs) and `market-brief`
   (`marketing` on its Tier-2 fixture with a **deterministic** named-competitor check). The
   `release` filename uses the skill's `review` collision fix: `security-review`'s phase prompt
   directs output to `security-review.md` (both review skills otherwise default to `review.md`).

5. **Cost-gated, on-demand.** Each phase is a full `claude` session (≈ one spine-phase-equivalent);
   scenarios run only via `eval.yml`, like the spine. The free `--runner dry` wiring check stays
   always-on (and asserts the `gh`/`GRAFANA_URL` neutralization in the `ops-incident` prompts).

## Alternatives considered

- **Per-skill E2E for all eight domains:** rejected — duplicates Tier-2 for the six skills that
  have it; the untested surface is the cross-domain handoff (and the two Tier-1-only orchestrators).
- **One bespoke runner per scenario (no shared model):** rejected — `spine_e2e.py` is already
  partly data-driven; a `Scenario` registry keeps the spine and new scenarios on one tested path.
- **LLM-judged checkpoints (reuse the Tier-2 grader):** rejected for the *gate* — Tier-3's value
  is deterministic outcome validation; judging would re-introduce Tier-2's variance and blur the
  tiers. Where a check is inherently semantic, it is reduced to a deterministic substring/keyword
  form (§3) rather than handed to a judge.
- **Stubbed-upstream phases** (run only the phase under test live, feed it a fixed upstream
  artifact): rejected as the *primary* design but kept as the **unit-test** layer (exit criterion 1)
  — only a fully-live chain proves a skill actually consumes the real prior artifact rather than a
  clean stub; stubbing is right for cheap plumbing tests, not for the E2E gate.
- **Exclude `marketing`:** rejected. An earlier draft excluded it as "live web research, already
  judged at Tier-2" — but `marketing`'s Tier-2 runs on a **static fixture** with
  citation-grounded assertions (name the competitors from the notes; no fabricated TAM), so a
  **deterministic** named-competitor check is feasible and adds something the LLM-judged Tier-2
  cannot guarantee. Included as `market-brief`. (The same honesty applies to `research`: it is a
  spine skill already gated by the spine Tier-3, so it appears in `product-inception` only as a
  carrier, never re-gated by a schema-only check.)
- **Re-run the full spine inside `quality-gate`:** rejected — wasteful; seed the existing spine
  artifacts and start from the quality/ops tail.

## Consequences

- Tier-3 grows from one scenario to five; the spine refactors onto the shared `Scenario` model
  (behaviour-preserving for the spine path; new plumbing separately tested).
- **All eight domains gain end-to-end coverage:** qa-test-strategy + security-review (quality-gate,
  the only gate beyond their Tier-1); deploy-watch + incident-response + release (ops-incident +
  quality-gate); repo-onboarding + ux-design (product-inception); marketing (market-brief).
- New fixtures/runner work: a `quality-gate` workspace (tagged `v1.0.0` baseline + an isolated
  planted-defect module + per-line→per-commit release replay) and a minimal `ops-incident`
  workspace (no git repo for phases 1–2). Tagging and the planted defect are **runner/seed** work,
  not "fixtures".
- `eval-runbook.md`'s "fork-orchestrators are Tier-1-only by design" line must be updated to
  "Tier-1-only at the skill-Tier-2 level; gated end-to-end by Tier-3 + the role's agent Tier-2"
  once this ships (tracked in the design doc's exit criteria).
- Implementation still follows contract → evals → implementation → gate, with a recorded live run
  and unit tests on stubbed phases (≥ 80% coverage), per [domain-e2e.md](../domain-e2e.md).
