# Domain E2E — Tier-3 scenarios for the Stage 4–6 domains

Status: **Designed, not built** ([ADR 0030](decisions/0030-domain-e2e-scenarios.md)); revised after a
deep multi-reviewer review (see the CHANGELOG entry). This doc is the contract for the work: goal,
scope, scenario contracts, checkpoints, the runner shape, and the exit criteria. Implement after
this is agreed (contract → evals → implementation → gate).

## Goal

Extend Tier-3 (end-to-end) coverage from the SDLC spine to the eight **Stage 4–6 domain skills**
(`qa-test-strategy`, `security-review`, `deploy-watch`, `incident-response`, `release`,
`marketing`, `ux-design`, `repo-onboarding`). All eight are in scope. These skills have Tier-1
(routing) and most have Tier-2 (LLM-judged quality), but no end-to-end scenario that drives them
on a realistic fixture and validates concrete artifacts and outcomes.

## What Tier-3 is today, and the gap

Today there is one Tier-3 scenario — the **SDLC spine** ([spine.md](spine.md),
`lib/agentic_forge/spine_e2e.py`): one feature carried through the six phases on an isolated copy
of the `taskstore` fixture, with deterministic per-phase checkpoints (each handoff artifact
validates; `develop`'s code implements the feature and the repo test suite passes; `code-review`
emits a verdict). What Tier-3 adds over the lower tiers, and where the gap is:

- **Cross-domain handoffs** — untested by Tier-0/1/2 (each is single-skill); the spine never
  touches the new domains.
- **Deterministic outcome checks** — a computed semver bump, an enum severity, a clean vault, a
  found planted defect — which Tier-2's LLM judge does not make.

## Approach: chains where the value is the handoff; deterministic checkpoints

A per-skill E2E would **largely duplicate Tier-2 for the six domains that already have a
fixture-backed Tier-2** (`release`, `deploy-watch`, `incident-response`, `marketing`, `ux-design`,
`repo-onboarding`). The two **fork-orchestrators** (`qa-test-strategy`, `security-review`) are
**Tier-1-only** by design ([ADR 0021](decisions/0021-stage4-ops-seam-and-eval-tiers.md)) — they
have no skill Tier-2 — so their end-to-end behaviour is genuinely uncovered. So Tier-3 grows by a
few multi-skill **chains** (for the handoffs + the un-covered orchestrators) plus a couple of
**deterministic single-skill complements** (where a deterministic check adds something Tier-2's
judge can't), not per-skill repeats.

### The `Scenario` abstraction (a real refactor, not a rename)

`spine_e2e.py` is partly data-driven (`PHASES`, `CHECKS`, `_phase_prompt` dicts) but hardcodes
`FEATURE_SLUG` / `FIXTURE_REPO` / `PHASES` as **module constants**, the `check_*` helpers and
`_phase_prompt` close over `FEATURE_SLUG`, `run_e2e` never passes `seed`, and `prepare_workspace`'s
`seed` only writes under `docs/sdlc/<slug>/`. Generalizing is therefore an **extension**, not a
rename:

```text
Phase    = { skill, prompt, checks(repo) -> [Checkpoint] }
Scenario = { name, fixture, slug, phases[], seed[] }
run_scenario(plugin_dir, scenario, *, run_phase, workspace) -> [PhaseResult]
```

Concretely: make `FEATURE_SLUG`/`FIXTURE_REPO`/`PHASES` into `Scenario` fields; thread `slug`/
`fixture` through `prepare_workspace`, the `check_*` helpers, `_phase_prompt`, and `check_wiring`;
extend `seed` to accept **arbitrary destination paths** (the ops JSON and onboarding sources land
at the repo root / a chosen path, not only `docs/sdlc/<slug>/`); and add a baseline-tag + commit
step for chains ending in `release` (below). The `claude` runner seam, `Checkpoint`/`PhaseResult`,
the dry-run wiring check, and the `handoff` / `vault` / `ops` / `release` validators are reused.
The spine becomes one registered `Scenario`; `tests/test_spine_e2e.py` guards the **spine path**,
and the **new `seed`/multi-scenario plumbing gets its own stubbed-phase unit tests** (the spine
test does not exercise it). Also fix the stale `run_e2e` "three-phase" docstring during the
refactor.

## Checkpoint determinism (the gate uses no LLM judge)

Every checkpoint is one of three deterministic kinds — none calls an LLM judge:

- **(D)** code comparison — compare an artifact field to a value the lib computes
  (`release.summarize(...).version`; `ops.classify_incident(...)`; `ops.rollout_health(...)`;
  `vault.validate_vault`; the repo `pytest` run).
- **(D-sub)** substring/location match on the model's artifact (a planted sink's path/symbol
  appears in `findings[].location`; named competitors appear in the `market-brief`).
- **(carrier)** schema-only validation of a handoff whose own quality is gated elsewhere (a spine
  phase reused inside a domain chain only to exercise the handoff).

## Wave 1

### `quality-gate` — quality/ops tail on a feature

Workspace: a copy of `spine/target-repo`; the **seed step creates a tagged baseline `v1.0.0`**
(baseline ≥ 1.0 so a `feat!:` correctly bumps major), seeds `spine/prd.md` + `spine/tech-design.md`
into `docs/sdlc/<slug>/`, and commits an **isolated planted-defect module** (a standalone
`user_lookup.py` modelled on `eval/fixtures/security-engineer/case1-sqli.py`, imported by **no
test** so the suite stays green, and **outside** `taskstore.py` so `develop` doesn't touch it).

| # | Phase | Checkpoint | Type |
| --- | --- | --- | --- |
| 1 | `qa-test-strategy` | `test-strategy.md` valid; `test_levels` non-empty; `risks` references a known risk keyword for the scenario (note: the schema does **not** enforce `risks` non-empty, so the checkpoint asserts it) | D / D-sub |
| 2 | `develop` | feature implemented in `taskstore.py`; repo `pytest` suite green (reuse `check_develop`; the planted module is un-imported, so it can't break the suite) | D |
| 3 | `security-review` | the phase **prompt** directs output to `security-review.md` (NOT the skill's default `review.md` — see below); valid `review` artifact; `findings[].location` references the planted sink (`user_lookup.py` / its query symbol) | D-sub |
| 4 | `code-review` | `review.md` valid; `verdict` ∈ `VERDICTS` (reuse `check_code_review`) | D |
| 5 | `release` | `release.md` valid; `version` == `release.summarize("1.0.0", commits_since(repo,"v1.0.0")).version` (the seed replays each fixture commit line as its own commit) | D |

**Filename collision (must be handled):** both `security-review` and `code-review` default to
writing `review.md` (`security-review`'s eval literally says "record review.md"; one shared
`review` schema, no security variant). In one `docs/sdlc/<slug>/` the second would overwrite the
first. The scenario's **phase prompt for `security-review` must override the path** to
`security-review.md` (the prompt is the only lever, as `_phase_prompt` already is for the spine),
and the security checkpoint needs its own checker (validate `review` + the planted-sink location).

### `ops-incident` — operations lifecycle, artifact-driven (no app repo for phases 1–2)

Each phase **prompt forces the in-memory source** (read the seeded JSON / markdown into
`ops.InMemoryPipeline` / `ops.InMemoryAlerts`) and **neutralizes `gh` / `GRAFANA_URL`** — otherwise
`connectors.pipeline_source` auto-detects a runner-present `gh` and silently queries the CI repo
instead of the fixture. The dry-run check asserts the neutralization is present in the prompts.

| # | Phase | Checkpoint | Type |
| --- | --- | --- | --- |
| 1 | `deploy-watch` | `deploy-status.md` valid; **`pipeline` field** == `"failing"` (the health label lives in `pipeline`, not a `health` key; expected derived via `ops.rollout_health` on `prod-failing.json`; `pipeline` is typed string-or-object, so the check handles the string form) | D |
| 2 | `incident-response` | `incident.md` valid; `severity` == `ops.classify_incident(outage=True)` == `"sev1"` | D |
| 3 | `release` | hotfix `release.md` valid (semver + ≥ 1 changelog group) — **schema-only here** (no baseline to compute an exact bump; weaker than quality-gate's step 5, stated honestly) | carrier |

**Handoff check (so the chain tests the handoff, not just sequential files):** assert
`incident.md`'s impact/timeline references the failing environment named in `deploy-status.md`
(D-sub). `degraded-scenario.md` + `prod-healthy.json` exist for an optional second, non-failing
case (`classify_incident(degraded=True, workaround=True)` == `sev3`).

## Wave 2

### `product-inception` — onboarding + UX in a chain (spine phases as carriers)

| # | Phase | Checkpoint | Type |
| --- | --- | --- | --- |
| 1 | `repo-onboarding` | `onboarding.md` valid; vault passes `validate_vault` (notes built via `vault.add_note` so the no-orphans rule holds) | D |
| 2 | `research` | `research-brief.md` valid | carrier (spine-gated) |
| 3 | `product` | `prd.md` valid | carrier |
| 4 | `ux-design` | `ux-spec.md` valid; `flows` non-empty (schema) + `accessibility` non-empty (checkpoint; schema doesn't enforce it) | D |
| 5 | `architecture` | `tech-design.md` valid + ≥ 1 ADR; references a `ux-spec` flow/screen (content-linkage) | D / D-sub |

`research`/`product`/`architecture` are **carriers** — included only to exercise the
onboarding → … → ux → architecture handoffs; their own quality is gated by the spine Tier-3, not
re-gated here.

### `market-brief` — `marketing` as a deterministic complement to its Tier-2

`marketing` already has a fixture-backed Tier-2 (its cases run on `market-notes.md` with
citation-grounded LLM-judged assertions). Tier-3 adds a **deterministic** complement on the same
fixture — single phase, no live web:

| # | Phase | Checkpoint | Type |
| --- | --- | --- | --- |
| 1 | `marketing` | `market-brief.md` valid; `competitors` include `{Algolia, Elastic, Typesense}` from the seeded notes; no fabricated TAM (the notes state none) | D-sub |

This complements (does not replace) marketing's Tier-2: it pins the citation-grounded outcome
deterministically, which the LLM-judged Tier-2 cannot guarantee.

## Fixtures

**Reused (exist):** `deploy-watch/prod-failing.json` (+`prod-healthy.json`),
`incident-response/outage-scenario.md` (+`degraded-scenario.md`), `release/commits*.txt`,
`repo-onboarding/{app,worker}.py`, `ux-design/feature.md`, `security-engineer/case1-sqli.py`,
`marketing/market-notes.md`, `spine/{prd,tech-design}.md`, `spine/target-repo`.

**To add (runner/seed work, not just files):** the `quality-gate` workspace = `spine/target-repo`
+ a **tagged `v1.0.0` baseline created in the seed step** + a committed **isolated planted-defect
module**, with the **per-line → per-commit replay** of the release fixture; a minimal
`ops-incident` workspace (just the two seeded files — **no git repo** for phases 1–2).

## Runner & CLI

`dev/run_spine_e2e.py` gains `--scenario {spine,quality-gate,ops-incident,product-inception,market-brief}`
(default `spine`, repeatable); `--runner dry|claude`, `--model`, `--workspace` unchanged. `--runner
dry` checks each selected scenario's wiring (skills + fixtures present) **and** that the
`gh`/`GRAFANA_URL` neutralization is present in the `ops-incident` phase prompts — no model calls,
always-on in CI.

## Where this sits in the eval pyramid

Tier-0 (schema/lint) and Tier-1 (routing) already cover these skills; six have Tier-2. This adds
**Tier-3** only; the four tiers stay as defined in [overview.md](overview.md). It is breadth (more
Tier-3 scenarios), not a new tier.

## Exit criteria

1. The `Scenario` refactor lands with the spine scenario green and `tests/test_spine_e2e.py`
   unchanged in intent; the **new `seed`/multi-scenario plumbing has its own stubbed-phase unit
   tests** (coverage ≥ 80%).
2. Wave-1 scenarios (`quality-gate`, `ops-incident`) pass `--runner dry` in CI and have a recorded
   live `--runner claude` run (numbers in the CHANGELOG).
3. Update `eval-runbook.md`'s "the fork-orchestrators … are Tier-1-only by design" line to
   "Tier-1-only **at the skill-Tier-2 level**; gated end-to-end by the Tier-3 domain scenario +
   the forked role's agent Tier-2" once Tier-3 lands (otherwise that line becomes misleading).
4. Wired into `eval.yml` (on-demand / `eval` label, cost-gated) alongside the spine.
5. Wave 2 (`product-inception`, `market-brief`) follows the same bar in a second increment.

## Cost

Each phase is a full `claude` session (`max_turns=40`) ≈ one spine-phase-equivalent. Wave-1 ≈ 8
sessions (`quality-gate` 5 + `ops-incident` 3) ≈ **one extra spine-equivalent run**; wave-2 adds
~6. Strictly **on-demand** in CI; the `dry` wiring check stays free and always-on.

## Alternatives

See [ADR 0030](decisions/0030-domain-e2e-scenarios.md) — per-skill vs chains; one generic scenario
vs a registry; deterministic vs LLM-judged checkpoints; **stubbed-upstream phases** (run only the
phase under test live, feed it a fixed upstream artifact); whether to include `marketing`.
