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
| 4 | Quality & operations domains | Built — 5 skills (qa-test-strategy, security-review, deploy-watch, incident-response, release) + ops/release lib cores; Tier-1/Tier-2 gated (ADR 0021, [quality-ops.md](architecture/quality-ops.md)) |
| 5 | Product & marketing domains | Built — product already covered by the `product` spine skill; `marketing` router skill (market-research / strategy / content) shipped, evidence-first, Tier-1/Tier-2 gated (ADR 0022, [product-marketing.md](architecture/product-marketing.md)) |
| 6 | Design & onboarding domains | Built — `ux-design` (ux-spec, specs not pixels) + `repo-onboarding` (analyze a codebase + seed the vault); Tier-1/Tier-2 gated (ADR 0023, [design-onboarding.md](architecture/design-onboarding.md)) |
| 7 | Guardrails, observability, scheduling (L4) | Built — four guardrail hooks (ADR 0019) + scheduling & observability (ADR 0024): declarative job registry + audit-log digest + cron CI |
| — | Post-spine increments | Built — increments through ADR 0040 (connectors, Tier-1 mean-rate, domain E2E, cadence persistence, quality-hardening, ultra-review, **eval A/B + token-overhead, review passes, diagnostics channel + review-scan**); see [Post-spine increments](#post-spine-increments-beyond-the-staged-plan) |
| — | Planned increments | **Planned** — PR watcher, external reviewer (codex), settings/config, multi-model tiers; see [Planned increments](#planned-increments-not-yet-built) |

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
specificity, scored as the mean per-prompt routing rate — ADR 0026), joined by schema-validated handoff artifacts, atop
the `software-engineer`/`security-engineer`/`qa-engineer` roles, the `engineering-standards`
skill, and the fan-out/multi-aspect-review patterns. The **full six-phase spine is proven end-to-end** (Tier-3: the `--runner claude` scenario
carried a feature from `FEATURE_REQUEST` through all six phases on a fixture repo — each handoff
schema-valid, code passing the repo suite, review approved; see CHANGELOG). The **by-stack
mechanism is built** (ADR 0015): deterministic `stacks.detect`, a `*-patterns` pack for **every
registered stack** (python, typescript, javascript, go, rust, jvm, dotnet, ruby, php), and
`develop`/`code-review`/roles consuming the stack profile; the E2E fixture is detected as Python.
The **Tier-1 trigger runner on live descriptions is built** (ADR 0016): `dev/run_tier1_evals.py`
gates every on-listing router skill's recall/specificity ≥ 0.9 against the real listing
(seventeen on-listing skills as of Stage 6), replacing the earlier router sim and the CI TODO. The **skill Tier-2 runner is built too**
(ADR 0017): `dev/run_skill_evals.py` runs the tier2 skills' contracts — knowledge skills as the
software-engineer with them loaded, `deep-review`/`skill-factory` directly — so **all four tiers
now have automated runners**. **Remaining:** a `*-patterns` pack for any new stack later added to
the registry; Layer 4 (guardrail hooks).

Goal: one continuous path from idea to reviewed code, proving the architecture end to end.

Dependencies: Stage 1; benefits from Stage 3 but should not block on it.

Scope: workflow skills `research → product → architecture → plan → develop → code-review`,
handing off artifacts phase to phase. Delegation targets are the Stage 1 set plus Stage 2
additions: built-in `Explore`/`Plan`, dedicated `architect`, `software-engineer` (renamed from
`implementer`), `reviewer`, `grader`, and the new `security-engineer` / `qa-engineer` — added
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

Status: **Built and gated** (ADR 0021). Five phase-workflow skills shipped — `qa-test-strategy`
and `security-review` (Tier-1 fork-orchestrators of qa-engineer / security-engineer),
`deploy-watch`, `incident-response`, and `release` (Tier-1 + Tier-2 own-behavior, on the tested
`ops` / `release` lib cores). Final gate (`claude-opus-4-8`): Tier-2 lower bound 1.000 for the
three own-behavior skills (n=5); Tier-1 recall 1.000 / specificity 1.000 for all five (runs=5).

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

Status: **Built and gated** (ADR 0022, [product-marketing.md](architecture/product-marketing.md)).
The product half is already shipped (the `product` spine skill does research → PRD with metrics),
so Stage 5 is the **marketing** domain: one evidence-first `marketing` router skill
(market-research / strategy / content as references), with `market-brief` / `marketing-strategy`
handoff types. Final gate (`claude-opus-4-8`): Tier-2 lower bound 1.000 (n=5); Tier-1 recall 1.000
/ specificity 1.000 (runs=5).

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

Status: **Built and gated** (ADR 0023, [design-onboarding.md](architecture/design-onboarding.md)).
`ux-design` (own behavior → a `ux-spec`: flows, screens/states, accessibility — specs not pixels)
and `repo-onboarding` (forks `Explore` to analyze an unfamiliar codebase and seeds the Stage-3
vault, emitting an `onboarding` map). Final gate (`claude-opus-4-8`): Tier-2 lower bound 1.000
(n=5) each; Tier-1 recall 1.000 / specificity 1.000 (runs=5) each.

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

Status: **Built** — the four guardrail hooks (ADR 0019: security, test-gate, logging, budget under
`plugin/hooks/`; see [guardrails.md](architecture/guardrails.md)) **and scheduling & observability**
(ADR 0024, [scheduling-observability.md](architecture/scheduling-observability.md)): a declarative
scheduled-job registry + pure due-logic (`schedule.py`), an audit-log digest (`observability.py`),
the `run_scheduled` / `audit_digest` CLIs, and a cron-triggered CI workflow. A richer observability
dashboard remains an optional follow-on.

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

## Post-spine increments (beyond the staged plan)

Cross-cutting increments beyond the staged plan, recorded by ADR + CHANGELOG:

- **Real provider connectors** — Built (ADR 0025, [architecture/connectors.md](architecture/connectors.md)).
  Concrete implementations of the existing `ops`/marketing seams: `GhPipelineSource` (GitHub
  Actions), `GrafanaAlertSource` (MCP-first + REST), and `marketing` → live `WebSearch`. Each a
  pure parser + a thin fetch seam; no skill/schema change. The `ops` Protocols stay
  provider-agnostic, so a new provider can be added if a concrete need arises (not planned).
- **Tier-1 metric refinement** — Built (ADR 0026), with the routing-remediation playbook in
  ADR 0029 (sharpen descriptions; reword only genuinely-ambiguous prompts) that brought all
  seventeen on-listing skills to ≥ 0.9 under the stricter metric. Tier-1 recall/specificity are
  the **mean per-prompt routing rate** over N samples (threshold 0.9 unchanged), replacing the
  brittle per-prompt majority-of-N: stabler and stricter.
- **Domain E2E (Tier-3 for Stage 4–6)** — **Built** (ADR 0030,
  [architecture/domain-e2e.md](architecture/domain-e2e.md)); design hardened by a deep
  multi-reviewer pass. `spine_e2e` generalized into a `Scenario` registry with five scenarios
  (`spine` + `quality-gate`, `ops-incident`, `product-inception`, `market-brief` — the last a
  deterministic `marketing` complement), judge-free checkpoints (code comparison / location
  substring / carrier schema), unit-tested on stubbed phases, wired into `eval.yml`. The recorded
  live `--runner claude` run is on-demand.
- **Scheduling cadence persistence** — Built (ADR 0031, extends 0024). Per-job `JobState`
  (`last_run`/`status`/`runs`/`failures`) replaces the flat last-run map; `due_jobs` retries a
  failed job on the next poll (bounded by `MAX_RETRIES`) and the runner records each outcome;
  legacy state files migrate on load. Plus a scheduled-job **health report** (`--health`).
  Anchored/drift-free schedules and per-environment keys are deferred behind the same state shape.
- **Quality-hardening increments** — **Built** (ADR 0032/0033/0034,
  [architecture/quality-hardening.md](architecture/quality-hardening.md)): a **handoff-contract
  guard** (skill bodies must document their artifact's required fields — the root cause behind the
  live-sweep `ux-design` flakiness), **knowledge recall** wired into the spine phases (read the
  vault to enrich context), and **develop parallelism** (independent plan tasks across worktrees via
  a tested `plan_batches`). Independent increments; built and closed by a deep multi-reviewer review.
- **Ultra-review hardening** — **Built / closed** (ADR 0035). A multi-lens adversarial review of the
  whole session, followed by an independent final pass over its own remediation diff, fixing real
  gate-integrity, security, and doc-honesty defects: the eval gate now **fails** a vacuous Tier-2
  contract (schema `required` sub-fields) instead of rubber-stamping it; `gate.all_passed([])` is
  False and the `dev/` runners are coverage-gated; secret redaction covers modern token shapes
  (incl. `sk-ant-…`, Stripe `rk_`) without over-redacting, and the danger deny-list runs **per shell
  segment** and is ReDoS-free; the LLM-judge transports + the `expected_release_version` / develop
  checkpoints are now genuinely tested (not tautological); and CLAUDE.md, the ADR index, and the
  pattern/skill docs were corrected to match the code (delegation via `Task`, not unused
  `context: fork`). Every finding verified against source; the suite is green, library 100% /
  aggregate 98% coverage. Nothing from the review remains open.
- **Eval-pyramid + diagnostics increments** — **Built** (ADR 0036–0040). The Tier-2 **A/B lift +
  time/token overhead** are now wired into the runners behind an opt-in `--baseline` (ADR 0036 +
  0038: a `RunOutput` usage seam, only version-over-version A/B still deferred); a bounded
  **adversarial skeptic review pass** was added to the artifact-writer workflows `product` /
  `marketing` / `ux-design` (ADR 0037); and an opt-in **self-diagnostics channel** captures the
  plugin's own errors / denials / anomalies → `diagnostics.jsonl` + a "top problems" digest
  (ADR 0039), including a deterministic **review-loop non-convergence scan** over `review.md`
  artifacts (ADR 0040).

---

## Planned increments (not yet built)

The next cross-cutting increments, captured here for analysis **before any code** (per the principle
above — open design questions are resolved first; each gets its own ADR + eval gate when picked up).
**Suggested build order:** settings (3) is foundational — it configures the others — so build it
first, then the external reviewer (2) and multi-model support (4) it gates, then the PR watcher (1,
the largest, which composes connectors + the fix loop + outward actions).

### 1 — PR watcher (monitor a GitHub PR, fix loop)

- **Goal:** an automated agent that watches a GitHub PR and, **hourly**, reads its review comments +
  merge conflicts and runs a **bounded fix loop** — for each reviewer comment, either fix it or
  reject it with a reasoned reply, then resolve the thread; and resolve merge conflicts.
- **Fit / deps:** composes a **GitHub PR connector** (review threads, mergeability, push — extends
  `connectors.py`, which already has the Actions source), the **`develop` fix loop** + worktree
  isolation (apply fixes on the PR branch), the **review-loop** bound, the **diagnostics** channel
  (record comments it can't resolve), and the **scheduler** — but **hourly** is finer than the
  current daily/weekly/monthly cadences, so it needs an `hourly` cadence (or a dedicated hourly
  GitHub-Actions cron; the "no daemon" constraint of ADR 0024 still holds — a cron-triggered
  headless run).
- **Open questions (largest item — most to resolve):**
  - **Outward-action policy** — posting replies, resolving threads, and pushing commits are GitHub
    *writes*: how much autonomy (auto-push vs propose), what auth/permissions, what guardrail (the
    "confirm outward actions" discipline applies strongly).
  - **Comment classification** — actionable-fix vs discussion vs already-addressed; the
    fix-vs-reject decision (a judgment for the `reviewer` role or a new agent).
  - **Idempotency / loop safety** — don't re-fix a resolved comment; don't thrash the PR (bounded).
  - **Conflict resolution** — mechanical vs `software-engineer`; when to give up and surface.
- **Risks:** runaway outward actions; mis-resolving a valid comment; permissions. **Mitigation:**
  opt-in, a dry-run mode, bounded, human-gated writes, a diagnostic on anything non-resolvable.

### 2 — External reviewer (codex) as a subagent

- **Goal:** run an external reviewer CLI — `codex` only, for now — as a subagent, usable to review
  code, a plan, and product / technical documents.
- **Fit / deps:** a new reviewer **seam** beside the internal `reviewer` role, mirroring the
  `claude_cli_runner` transport (a `codex_cli_runner`: shell out, parse its output into the
  canonical findings shape — `severity` / `location` / `issue` / `suggestion`). Plugs into
  `review-loop` / `multi-aspect-review` / `adversarial-review` as an **independent lens** (a
  different model raises recall — exactly what adversarial-review wants). Toggled by (3).
- **Open questions:** parsing codex output reliably into the `review` shape; where it plugs in (an
  extra lens in `deep-review`? an alternative reviewer in `develop`'s loop? both); graceful
  degradation when the CLI is absent/unauthed (the connectors pattern); cost vs independence; a
  seam that admits other external reviewers later.
- **Risks:** brittle output parsing; CLI unavailability. **Mitigation:** a pure parser + a thin
  fetch seam, degrade gracefully, opt-in.

### 3 — Plugin settings & configuration

- **Goal:** one structured, validated settings mechanism for the plugin's knobs — enable the
  diagnostics / log collector, enable the external reviewer (+ which), set the review passes (the
  review-loop `N`), model tiers (see 4), and migrate the scattered env vars
  (`AGENTIC_FORGE_DIAGNOSTICS` / `…_SUBAGENT_SOFT|HARD` / `…_SKIP_TEST_GATE`).
- **Fit / deps:** config today is ad-hoc env vars. This adds a tested `lib/settings.py` (pure
  load / merge / validate) reading a per-repo `.agentic-forge/config.*` with precedence
  **defaults < file < env** (keep env overrides for back-compat) + a JSON schema. **Foundational**
  for 1 / 2 / 4, which read their toggles from it.
- **Open questions:** format (TOML vs JSON) + location; the curated key set; per-skill vs global
  review `N`; never crash on a bad config (degrade to defaults + emit a diagnostic).
- **Risks:** config sprawl / precedence confusion. **Mitigation:** a small key set, defaults =
  today's behaviour, one documented precedence order.

### 4 — Multi-model support (tier by task complexity)

- **Goal:** use cheaper models (sonnet / haiku) for simpler work and the strongest (opus) for hard
  work — e.g. routing / grading / recall / simple synthesis on a cheap tier; implementation /
  design / security / adversarial review on opus.
- **Fit / deps:** the `model` frontmatter field already exists and the runners take `--model`; this
  makes tiering a **deliberate, configurable policy** — a default tier per role / skill (read from
  3), honoured by `Task` delegations and the runners. The `--baseline` A/B (ADR 0036) measures the
  quality / cost trade-off per tier.
- **Open questions:** which work is "simple enough" for a cheap tier (validated by Tier-2 *at that
  tier* — it must still clear the bar, else the role isn't eligible); mechanism (per-component
  `model` vs a settings tier map vs both); re-recording the model-dependent Tier-1 / Tier-2 per tier.
- **Risks:** a cheaper model silently dropping below the gate. **Mitigation:** the eval-driven rule
  protects it — only downgrade a role / skill where its Tier-2 still passes at the cheaper tier.

---

## Cross-stage definition of done

A stage is done only when every component it ships passes its full eval gate, its docs are
written (vision/architecture/this roadmap updated, CHANGELOG entry added), and CI is green.
