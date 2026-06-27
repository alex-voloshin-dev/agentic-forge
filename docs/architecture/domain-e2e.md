# Domain E2E — Tier-3 scenarios for the Stage 4–6 domains

Status: **Designed, not built** ([ADR 0030](decisions/0030-domain-e2e-scenarios.md)). This doc is
the contract for the work: goal, scope, scenario contracts, checkpoints, the runner shape, and
the exit criteria. Implement after this is agreed (contract → evals → implementation → gate).

## Goal

Extend Tier-3 (end-to-end) coverage from the SDLC spine to the **Stage 4–6 domains**
(`qa-test-strategy`, `security-review`, `deploy-watch`, `incident-response`, `release`,
`marketing`, `ux-design`, `repo-onboarding`). These skills have Tier-1 (routing) and most have
Tier-2 (LLM-judged quality), but **no end-to-end scenario** that drives them on a realistic
fixture and validates concrete artifacts and outcomes.

## What Tier-3 is today, and the gap

Today there is one Tier-3 scenario — the **SDLC spine** ([spine.md](spine.md),
`lib/agentic_forge/spine_e2e.py`): one feature (`task-priorities`) carried through the six
phases on an isolated copy of the `taskstore` fixture, with **deterministic per-phase
checkpoints** (each handoff artifact validates; `develop`'s code implements the feature and the
repo test suite passes; `code-review` emits a verdict).

Two gaps:

1. **The new domains aren't in any Tier-3.** The spine scenario never touches them.
2. **Tier-2 ≠ Tier-3.** Tier-2 runs a *single* skill and grades its output with an LLM judge.
   Tier-3 tests **realistic chains** and validates **concrete outcomes deterministically** (a
   semver bump computed exactly, a vault that passes `validate_vault`, a severity in the enum, a
   health label that matches canned data, a planted defect that is found). The handoffs *between*
   the new domains and the spine are untested by either.

## Approach: domain **chains**, not per-skill repeats

A per-skill E2E for each of the eight would largely duplicate Tier-2 (which already runs each on
a fixture). The value is in **chains** that exercise the handoffs between new domains and the
spine, plus **deterministic outcome checks** Tier-2's judge does not make. So Tier-3 grows by a
small set of multi-skill **scenarios**, each ending in validated artifacts/outcomes.

### The `Scenario` abstraction

`spine_e2e.py` is already data-driven (`PHASES`, `CHECKS`, per-phase prompts). Generalize it so
the spine becomes one registered scenario and new ones are added as data:

```text
Phase    = { skill, prompt, checks(repo) -> [Checkpoint] }
Scenario = { name, fixture, slug, phases[], seed[] }
run_scenario(plugin_dir, scenario, run_phase, workspace) -> [PhaseResult]
```

`run_phase` (the `claude` CLI seam), `prepare_workspace`, the `Checkpoint`/`PhaseResult` types,
the dry-run wiring check, and the `handoff.load_artifact` / `vault.validate_vault` validators are
all reused unchanged. The spine scenario is refactored onto this shape with **no behaviour
change** (its `tests/test_spine_e2e.py` stays green — the refactor's guard).

## Scenarios in scope

### Wave 1

**`quality-gate`** — quality/ops tail on a feature (seeds the existing spine artifacts to avoid
re-running the whole spine, then drives the new domains).

| Phase | Skill | Checkpoints (deterministic) | Fixture |
| --- | --- | --- | --- |
| 1 | `qa-test-strategy` | `test-strategy.md` validates (type, non-empty `test_levels`); names ≥1 real risk area | seeded `prd.md` + `tech-design.md` (exist) |
| 2 | `develop` | feature implemented in `taskstore.py`; repo test suite green (reuse `check_develop`) | `spine/target-repo` |
| 3 | `security-review` | `security-review.md` validates (type `review`, `verdict`); **finds the planted issue** | planted-defect variant of the repo |
| 4 | `code-review` | `review.md` validates; `verdict` ∈ `VERDICTS` (reuse `check_code_review`) | — |
| 5 | `release` | `release.md` validates (type `release`, semver `version`, ≥1 changelog group); **`version` = the exact bump `release.classify` computes from the commits since the baseline tag** | baseline tag + the feature commit |

**`ops-incident`** — operations lifecycle, artifact-driven (no app code needed).

| Phase | Skill | Checkpoints (deterministic) | Fixture |
| --- | --- | --- | --- |
| 1 | `deploy-watch` | `deploy-status.md` validates; health label == `failing` (matches the canned pipeline) | `deploy-watch/prod-failing.json` (exists) |
| 2 | `incident-response` | `incident.md` validates; `severity` ∈ `INCIDENT_SEVERITIES`; == the scenario's expected sev | `incident-response/outage-scenario.md` (exists) |
| 3 | `release` | hotfix `release.md` validates (semver + changelog) | commit fixtures (exist) |

### Wave 2

**`product-inception`** — front-of-lifecycle with onboarding + UX (threads two more domains onto
the spine's head).

| Phase | Skill | Checkpoints | Fixture |
| --- | --- | --- | --- |
| 1 | `repo-onboarding` | `onboarding.md` validates; **vault passes `validate_vault`** (linked, no orphans) | `repo-onboarding/{app,worker}.py` (exist) |
| 2 | `research` | `research-brief.md` validates (reuse `check_research`) | — |
| 3 | `product` | `prd.md` validates (reuse `check_product`) | — |
| 4 | `ux-design` | `ux-spec.md` validates (non-empty `flows`, `accessibility`) | `ux-design/feature.md` (exists) |
| 5 | `architecture` | `tech-design.md` validates + ≥1 ADR (reuse `check_architecture`) | — |

`marketing` is **out of Tier-3 scope**: its value depends on live web research (cited
competitors/sources), which is non-deterministic and already judged at Tier-2. Its artifacts
(`market-brief` / `marketing-strategy`) keep schema validation at Tier-0; no E2E.

## Determinism & planted defects

Checkpoints must be gradeable without an LLM judge (Tier-3 is deterministic, like the spine):

- **Schema** — every phase output validates via `handoff.load_artifact(type=…)`.
- **Computed outcomes** — `release` version equals `release.classify_*`'s exact bump; `incident`
  severity is in `INCIDENT_SEVERITIES` and matches the scripted scenario; `deploy-watch` health
  equals the canned pipeline's; `repo-onboarding` vault passes `validate_vault`.
- **Planted defects** — for `security-review`, ship a fixture variant with a known issue (e.g. an
  SQL-injection sink modelled on `eval/fixtures/security-engineer/case1-sqli.py`) and assert the
  artifact's findings reference its location — the same planted-defect technique
  [`deep-review`](../../plugin/skills/deep-review/evals/evals.json) uses.

## Runner & CLI

- Library: extend `spine_e2e.py` (or a sibling `domain_e2e.py`) with the `Scenario` model + a
  `SCENARIOS` registry; keep the spine as one entry.
- CLI: `dev/run_spine_e2e.py` gains `--scenario {spine,quality-gate,ops-incident,product-inception}`
  (default `spine`, repeatable); `--runner dry|claude`, `--model`, `--workspace` unchanged.
- `--runner dry` checks each selected scenario's wiring (skills present, fixtures present) with no
  model calls — runs in CI on every eval job, exactly as the spine does now.

## Fixtures

Most already exist (built for Tier-2): `deploy-watch/prod-failing.json`,
`incident-response/outage-scenario.md`, `release/commits*.txt`, `repo-onboarding/{app,worker}.py`,
`ux-design/feature.md`, `security-engineer/case1-sqli.py`. **To add:** a `quality-gate` target
repo (the spine `taskstore` + a tagged baseline) and its planted-defect variant for
`security-review`; a minimal `ops-incident` workspace holding the canned pipeline JSON + incident
script.

## Where this sits in the eval pyramid

Tier-0 (schema/lint) and Tier-1 (routing) already cover these skills; most have Tier-2 (quality).
This adds **Tier-3** only. The four tiers stay as defined in [overview.md](overview.md); this is
breadth (more Tier-3 scenarios), not a new tier.

## Exit criteria

1. The `Scenario` refactor lands with the spine scenario green and `tests/test_spine_e2e.py`
   unchanged in intent (the no-behaviour-change guard).
2. Wave-1 scenarios (`quality-gate`, `ops-incident`) pass `--runner dry` wiring in CI and have a
   **recorded live `--runner claude` run** (numbers in the CHANGELOG, per the eval-runbook).
3. Unit tests cover the runner + each scenario's checkpoints on **stubbed** phase outputs
   (pass + fail paths), mirroring `tests/test_spine_e2e.py`; coverage stays ≥ 80%.
4. Wired into `eval.yml` (on-demand / `eval`-label, cost-gated) alongside the spine.
5. Wave 2 (`product-inception`) follows the same bar in a second increment.

## Cost

Every phase is a full `claude` session (`max_turns=40`). Wave-1 ≈ 8 sessions per run
(`quality-gate` 5 + `ops-incident` 3); wave-2 adds ~5. Strictly **on-demand** in CI (never on the
always-on path), like the spine today. The `dry` wiring check stays free and always-on.

## Alternatives

See [ADR 0030](decisions/0030-domain-e2e-scenarios.md) for the alternatives weighed (per-skill
E2E vs chains; one generic scenario vs a registry; LLM-judged vs deterministic checkpoints;
including `marketing`).
