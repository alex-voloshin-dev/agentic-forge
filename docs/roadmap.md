# Roadmap & staged work plan

This is the plan from where we are to the product goal. Each stage is analyzed before it is
built: goal, dependencies, scope, the design questions to resolve first, the components it
produces, exit criteria (eval thresholds), and risks. We do not start implementation of a
stage until its open design questions are answered.

## Principle: thin vertical slice before broad fan-out

We build the minimum engine needed for one end-to-end SDLC path, prove the whole machinery
(router, subagents, handoff, review loop, worktree, eval gate, knowledge base) on a real
example, then fan out to the remaining domains using `skill-factory`. This de-risks the
architecture before we invest in breadth.

## Status summary

| Stage | Name | Status |
| --- | --- | --- |
| 0 | Meta-core (L0) | **Done** |
| 1 | Engine foundations (L1, minimal) | **Done** — see [engine.md](architecture/engine.md) |
| 2 | SDLC spine vertical slice (L2) | Built — six-phase spine proven E2E; by-stack complete: detection + a `*-patterns` pack for every registered stack (9) + wiring |
| 3 | Knowledge base (L3) | Built — vault lib + `knowledge` skill + session-start hook (ADR 0018) |
| 4 | Quality & operations domains | Planned |
| 5 | Product & marketing domains | Planned |
| 6 | Design & onboarding domains | Planned |
| 7 | Guardrails, observability, scheduling (L4) | Built — four guardrail hooks (ADR 0019); scheduling/observability deferred |

---

## Stage 0 — Meta-core (Done)

Goal: a tested foundation that builds and gates everything. Delivered the Tier-0 validator,
the shared library, the hybrid eval-harness (benchmark + gate), the `evals.json` superset
schema, and the `skill-factory` meta-skill, with CI. See
[architecture/meta-core.md](architecture/meta-core.md).

Exit criteria (met): `validate` clean, `pytest`/`ruff`/`mypy` green, `skill-factory` passes
its own Tier-0, plugin-integrity test in place.

---

## Stage 1 — Engine foundations (minimal)

Status: **Done.** Delivered the four roles (`reviewer`, `grader`, `software-engineer`,
`architect`) with narrowed tools, return contracts, and agent eval contracts under
`plugin/agents/evals/`; `lib/agentic_forge/handoff.py` with per-type header schemas (unit
tested at 100%); and the pattern references in `plugin/patterns/` (handoff, review loop,
worktree). Tier-0 is green. The agent Tier-2 quality runner is in place
(`dev/run_agent_evals.py`, wired into `eval.yml`). Tier-2 has been **executed** on a Claude
subscription (Opus 4.8): all four roles pass (lower bound ≥ 0.885; `grader` 0.954, the others
1.000) — see the CHANGELOG and [eval-runbook.md](eval-runbook.md).

Goal: the reusable execution machinery the first workflow slice needs — not every pattern,
only what Stage 2 consumes.

Dependencies: Stage 0.

Scope (in): a small set of subagent roles and the patterns that bind them — file-based
handoff between phases, a bounded review loop, and worktree isolation. Scope (out): Ralph
loops, fan-out research at scale, full role catalog (deferred to later stages).

Design questions: **resolved** in [architecture/engine.md](architecture/engine.md) and
[ADR 0009](architecture/decisions/0009-engine-roles-and-handoff.md). Summary: dedicated
roles `reviewer`, `grader`, `software-engineer`, `architect` (research/planning reuse built-in
`Explore`/`Plan`); handoff via Markdown + YAML frontmatter in `docs/sdlc/<slug>/`; review
loop bounded at N=3 with an approve signal; agent eval via the dedicated runner
(`agent_eval.py`) + our gate (ADR 0011).
The validator already enforces agent eval contracts (done during the review).

Components produced: four `plugin/agents/*.md` roles + their eval contracts at
`plugin/agents/evals/`, `lib/agentic_forge/handoff.py` + artifact header schemas, and
pattern references (review loop, worktree, handoff).

Exit criteria: each role has an `evals.json` (`component.type: agent`) and meets Tier-2 on
its task set; `handoff.py` + schemas implemented and unit-tested; patterns documented;
Tier-0 green.

Risks: over-building roles before a real workflow needs them. Mitigation: build strictly
what Stage 2 consumes.

---

## Stage 2 — SDLC spine vertical slice

Status: **all six phase skills built and gated.** `research → product → architecture → plan →
develop → code-review` are each a workflow skill passing Tier-0 + Tier-1 (≥ 0.9 recall/
specificity via majority-of-N router sims), joined by schema-validated handoff artifacts, atop
the `software-engineer`/`security-engineer`/`qa-engineer` roles, the `engineering-standards`
skill, and the fan-out/multi-aspect-review patterns. The **full six-phase spine is proven end-to-end** (Tier-3: the `--runner claude` scenario
carried a feature from `FEATURE_REQUEST` through all six phases on a fixture repo — each handoff
schema-valid, code passing the repo suite, review approved; see CHANGELOG). The **by-stack
mechanism is built** (ADR 0015): deterministic `stacks.detect`, a `*-patterns` pack for **every
registered stack** (python, typescript, javascript, go, rust, jvm, dotnet, ruby, php), and
`develop`/`code-review`/roles consuming the stack profile; the E2E fixture is detected as Python.
The **Tier-1 trigger runner on live descriptions is built** (ADR 0016): `dev/run_tier1_evals.py`
gates the nine on-listing router skills' recall/specificity ≥ 0.9 against the real listing,
replacing the earlier router sim and the CI TODO. The **skill Tier-2 runner is built too**
(ADR 0017): `dev/run_skill_evals.py` runs the tier2 skills' contracts — knowledge skills as the
software-engineer with them loaded, `deep-review`/`skill-factory` directly — so **all four tiers
now have automated runners**. **Remaining:** a `*-patterns` pack for any new stack later added to
the registry; Layer 4 (guardrail hooks).

Goal: one continuous path from idea to reviewed code, proving the architecture end to end.

Dependencies: Stage 1; benefits from Stage 3 but should not block on it.

Scope: workflow skills `research → product → architecture → plan → develop → code-review`,
handing off artifacts phase to phase. Delegation targets are the Stage 1 set plus Stage 2
additions: built-in `Explore`/`Plan`, dedicated `architect`, `software-engineer` (renamed from
`software-engineer`), `reviewer`, `grader`, and the new `security-engineer` / `qa-engineer` — added
per shipping phase and gated (see ADR 0013/0014). Stack specialization is via skills, not
per-stack agents.

Design questions: **resolved** in [architecture/spine.md](architecture/spine.md) and
[ADR 0013](architecture/decisions/0013-spine-workflow-chain.md) (supersedes 0012). Summary:
the spine is a **chain of phase-workflows** (each fans out subagents and synthesizes), named
`research, product, architecture, plan, develop, code-review`, joined only by handoff
artifacts; **fan-out/fan-in is core**; built fresh with `ai-skills` as reference; an expanded
specialist agent roster (gated per addition); trigger taxonomy by owned artifact (should-not
seeded from neighbours); E2E on a Python fixture target-repo; **build the thin slice
`architecture → develop → code-review` first**, multi-language (by-stack) after.

Components produced: six workflow skills, new specialist roles, fan-out/multi-aspect-review
patterns, evals, and shared trigger taxonomy.

Exit criteria: each skill meets Tier-1 (recall/specificity ≥ 0.9) and Tier-2 (≥ 0.8 lower
bound); the E2E scenario passes Tier-3 with all phase checkpoints green.

Risks: trigger overlap causing the wrong skill to load; phase artifacts too rigid or too
loose. Mitigation: design the trigger taxonomy and artifact schemas up front.

---

## Stage 3 — Knowledge base

Status: **Built** (ADR 0018) — the vault lib (`vault.py`), the `knowledge` recall/capture skill,
and the session-start injection hook (the plugin's first hook); see
[knowledge.md](architecture/knowledge.md).

Goal: an Obsidian-format vault the plugin deploys in the target repo, maintains, and reads
to enrich workflow context.

Dependencies: vault scaffolding, recall skill, and templates depend only on Stage 0 and can
be built independently. The **write path** (workflows writing artifacts/notes into the
vault) depends on Stage 2 existing. Treat these as two separable task groups.

Open design questions (resolve before building):
- **Vault location & structure.** `knowledge/` vs `.claude/knowledge/`; maps-of-content
  (MOC) index notes; `[[wikilinks]]` for humans while staying readable by Claude.
- **Read path.** How workflows pull relevant notes: a `user-invocable: false` recall skill,
  a SessionStart hook injecting the index, or both.
- **Write path & maintenance.** When workflows write notes; how a periodic re-scan keeps the
  vault current (delegated to CI/headless, since no native scheduler).
- **De-duplication / consolidation.** Avoiding sprawl as notes accumulate.

Components produced: KB scaffolding templates (`kb-template`), a recall skill, a maintenance
skill, optional SessionStart hook.

Exit criteria: vault auto-deploys; recall meets a retrieval-quality threshold on a fixture
set; maintenance run is idempotent.

Risks: KB sprawl and stale notes. Mitigation: MOC discipline + consolidation routine.

---

## Stage 4 — Quality & operations domains

Goal: `qa-test-strategy`, `security-review`, `deploy-watch`, `incident-response`, `release`.

Dependencies: Stages 1–2 (reuses roles, patterns, handoff).

Design: [architecture/quality-ops.md](architecture/quality-ops.md) — resolves the open
questions (ops via a tested adapter seam `lib/ops.py` with provider fakes; four-level incident
severity; semver + Keep-a-Changelog for `release`; scheduling deferred to Stage 7), with the five
skills' contracts, new handoff types, and the fixture-backed, inspection-gradeable eval plan.

Exit criteria: each skill meets Tier-1/Tier-2; integration points stubbed or wired with
tests.

Risks: external-system coupling. Mitigation: isolate integrations behind adapters; keep
core logic testable.

---

## Stage 5 — Product & marketing domains

Goal: `product` (research synthesis, metrics) and `marketing` (market, competitors,
strategy, content, social, paid).

Dependencies: Stages 1–3 (research roles, KB).

Open design questions: how much is reusable from the old repo's marketing/PM skills vs
rebuilt to the new gate; evidence/verification standards for market and competitor claims;
content output formats.

Exit criteria: Tier-1/Tier-2 per skill; claims-verification checks where applicable.

Risks: low-signal generated content. Mitigation: stronger rubrics and verification assertions.

---

## Stage 6 — Design & onboarding domains

Goal: `ux-design` (flows, design system, accessibility) and `repo-onboarding` (analyze an
unfamiliar codebase, seed the KB).

Dependencies: Stages 1–3; `repo-onboarding` feeds Stage 3.

Open design questions: how UI/UX outputs are represented (specs, not pixels) and handed to
`develop`; what `repo-onboarding` extracts and how it writes to the vault.

Exit criteria: Tier-1/Tier-2 per skill; onboarding produces a usable KB seed on a fixture
repo.

Risks: scope creep into visual design. Mitigation: keep outputs as specs and handoff docs.

---

## Stage 7 — Guardrails, observability, scheduling

Status: **Built (the guardrail hooks)** (ADR 0019) — security, test-gate, logging, and budget
hooks under `plugin/hooks/`; see [guardrails.md](architecture/guardrails.md). **Scheduling and
observability dashboards remain a follow-on** (not guardrails).

Goal: harden L4 — security hooks, a test/eval gate hook, action logging, subagent budgets —
and wire scheduled work via CI/headless runs.

Dependencies: all prior stages (hooks guard their behavior).

Open design questions: which guardrails are hooks vs rules; subagent budget policy;
scheduled jobs to run headless (KB re-scan, deploy-watch digests) and their cadence.

Exit criteria: hooks unit-tested (`pytest`), exit-code-2 blocking verified; scheduled
workflows defined and dry-run green.

Risks: over-restrictive hooks causing friction. Mitigation: warn-then-block rollout, tests
for both allow and block paths.

---

## Cross-stage definition of done

A stage is done only when every component it ships passes its full eval gate, its docs are
written (vision/architecture/this roadmap updated, CHANGELOG entry added), and CI is green.
