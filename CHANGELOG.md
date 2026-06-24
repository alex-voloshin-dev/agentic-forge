# Changelog

All notable changes to agentic-forge are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow semantic
versioning once it has a public surface.

## [Unreleased]

### Fixed — Tier-2 eval fidelity (skill quality gates)

A live Tier-2 run surfaced 7 skill gates below the 0.8 bar. Per-assertion root-causing showed
these were **eval-design** issues, not skill weakness — fixed by improving the skill or making
the eval a higher-fidelity test, **never by lowering the 0.8 threshold or dropping assertion
coverage** (per-case assertion counts are unchanged):

- **The read-only grader cannot execute toolchains.** The `grader` role has only
  `Read/Grep/Glob`, so assertions phrased as *executions* — "dotnet build is clean", "cargo
  clippy clean", "the project builds via its wrapper", "eslint clean", "dev/validate.py reports
  no errors", "ruff + mypy pass" — were never gradeable by running them; the grader could only
  guess, which is the near-0.8 variance. Each was reframed to the **inspectable code-property it
  proxies** (compiles cleanly / clippy-clean / no new `eslint-disable` / standard-compliant on
  inspection), preserving the quality intent. (dotnet, rust, jvm, javascript, skill-factory)
- **knowledge** — the executor looked for `lib/agentic_forge/vault.py` by path (absent in the
  sandbox) and hand-rolled notes with the wrong frontmatter. SKILL.md now invokes the
  **installed `agentic_forge.vault` module** and states the exact note frontmatter
  (`title`/`type`/`tags`), so both the validation run and the schema are satisfied.
- **skill-factory** — the body never stated where a subagent lives, so it scaffolded one at the
  wrong path; added the **canonical component-location table** (`plugin/agents/<name>.md`, …).
  An assertion demanding a `script`-type `evals.json` (a type the schema *reserves for future
  use*) was corrected to the real convention: scripts are contracted by **pytest**.
- **engineering-standards** — its empty-sandbox case made the software-engineer correctly refuse
  to "scaffold from nothing"; it now ships a real `cart.py`/`test_cart.py` fixture and a concrete
  task.
- **jvm-patterns** — case 2 now exercises a value-type map key, so the equals/hashCode assertion
  is actually tested rather than vacuously failing.
- **javascript-patterns** — sharpened the boundary-validation idiom: returning raw parsed
  `unknown`/`any` is explicitly *not* validation.
- **Applied uniformly (ADR 0020).** An audit of *every* skill's assertions found the same
  execution-phrasing in the 5 packs that *passed* (go, php, python, ruby, typescript) — latent
  flakiness that would surface on a future run. Reframed those too (faithfully, same strictness).
  Recorded the rule as
  [ADR 0020](docs/architecture/decisions/0020-tier2-inspection-gradeable-assertions.md) and in
  the eval-runbook: **a Tier-2 assertion must be verifiable by the read-only grader
  (`Read/Grep/Glob`) — it can never run a build/linter/test, so phrase the property for
  inspection, not execution.**

**Results** (model `claude-opus-4-8`; lower bound = `mean − stddev`, n = 5):

| Skill | Before (lower bound) | After (lower bound) |
| --- | --- | --- |
| skill-factory | 0.454 ❌ | **0.912** ✅ |
| engineering-standards | 0.571 ❌ | **0.836** ✅ |
| knowledge | 0.667 ❌ | **1.000** ✅ |
| jvm-patterns | 0.672 ❌ | **1.000** ✅ |
| javascript-patterns | 0.750 ❌ | **0.895** ✅ |
| rust-patterns | 0.778 ❌ | **0.861** ✅ |
| dotnet-patterns | 0.822 ❌ | **0.895** ✅ |

All seven now clear the gate (`mean − stddev ≥ 0.8`, n = 5). The five hardened packs that
already passed (go, php, python, ruby, typescript) each scored **1.000** on a 1× regression
check — the faithful reframe did not regress them. Combined with the agent Tier-2 (6/6 roles)
and the Tier-3 spine E2E (pass), the full eval suite is green.

### Added — Stage 4 quality & operations (design + foundation)

- **Stage 4 design** `docs/architecture/quality-ops.md`: the five quality/ops phase-workflows
  (`qa-test-strategy`, `security-review`, `deploy-watch`, `incident-response`, `release`) — each
  skill's contract (purpose, forked role, handoff artifact, trigger boundary), the ops adapter
  seam (`lib/ops.py` + provider fakes), the four-level incident severity model, release
  conventions (semver + Keep-a-Changelog), and a fixture-backed, inspection-gradeable eval plan.
- **Handoff artifact types** (`handoff.py`, contract-first, 100% covered): `test-strategy`,
  `release`, `incident` (with a four-level `INCIDENT_SEVERITIES` vocabulary `sev1`–`sev4`), and
  `deploy-status`; `security-review` reuses the existing `review` type. Schemas and tests landed
  before the skills, per the evals-first rule.
- **`release` core** `lib/agentic_forge/release.py` (100% covered): classify conventional commits
  → derive the semver bump (breaking → major, `feat` → minor, else patch; `0.y.z` breaking → minor)
  and a Keep-a-Changelog grouping (`**BREAKING:**`-flagged); a thin `commits_since` git seam keeps
  the logic unit-tested without a repo.
- **`ops` adapter seam** `lib/agentic_forge/ops.py` (100% covered): provider-agnostic
  `PipelineSource` / `AlertSource` (with `InMemory*` fakes for tests + eval fixtures) plus the
  deterministic assessment — `rollout_health`, `triage_alerts`, `deploy_status` (emits a
  schema-valid `deploy-status` mapping), and `classify_incident` (sev1–4). Keeps the
  `deploy-watch` / `incident-response` Tier-2 runnable with no live infra. (`deploy-status`
  `alerts` widened to list-or-dict to carry the triage counts.)
- **`release` skill** `plugin/skills/release/` (evals-first, fixture-backed): wires the `release`
  core to the repo — find the current version + commits since the last tag, derive the version,
  render the changelog and a `release` artifact, tag only on request. Tier-1 triggers + two
  inspection-gradeable Tier-2 cases (minor bump; breaking → major). The Stage-4 build template.

### Added — Layer 0 meta-core

- **Repository skeleton** for a Claude Code-only plugin: `plugin/` layout, `plugin.json`,
  `marketplace.json`, `pyproject.toml` (uv / pytest / ruff / mypy), `.gitignore`.
- **Project constitution** (`CLAUDE.md`): skill-centric + router discipline, eval-driven
  contract-first development, the four-tier eval pyramid, Python-only tested scripts,
  Obsidian knowledge base, layered architecture, editing rules.
- **Shared library** `plugin/lib/agentic_forge/`:
  - `naming.py` — Agent Skills name validation.
  - `frontmatter.py` — YAML frontmatter parsing.
  - `evals.py` — load + JSON-Schema validation of `evals.json`.
  - `validation.py` — Tier-0 checks for skills, agents, and the manifest.
  - `benchmark.py` — aggregate `grading.json` runs into benchmark statistics.
  - `gate.py` — threshold gate (Tier-1 trigger, Tier-2 quality, lower-bound rule).
- **Tier-0 validator CLI** `dev/validate.py`.
- **Eval contract schema** `plugin/schemas/evals.schema.json` — a superset of the
  skill-creator `evals.json` (adds `component`, `thresholds`, `triggers`).
- **`skill-factory` meta-skill** `plugin/skills/skill-factory/` — router-pattern SKILL.md,
  per-type references (skill / agent / script), the eval-loop guide, templates, and
  hand-written evals (bootstrap exception). Builds skills, subagents, and scripts.
- **Eval harness docs** `plugin/eval/README.md` — hybrid-on-skill-creator architecture.
- **Tests** (`tests/`): naming, frontmatter, evals, validation, benchmark, gate, and a
  plugin-integrity dogfood test that asserts the plugin passes its own Tier-0 gate.
- **CI** `.github/workflows/ci.yml` (Tier-0 on every push/PR) and `eval.yml` (Tier-1/2,
  cost-gated by `workflow_dispatch` or the `eval` PR label).
- **Documentation** under `docs/`: product vision, architecture overview, meta-core guide,
  eight ADRs, and this staged roadmap.

### Added — Stage 1 design

- **Engine design doc** `docs/architecture/engine.md`: role contracts (`reviewer`,
  `grader`, `implementer`, `architect`), markdown+frontmatter handoff artifact model and
  schemas, bounded review loop (N=3, approve signal), and agent-eval approach.
- **ADR 0009** recording the engine roles, handoff format, review loop, and agent eval.

### Added — Stage 1 engine foundations (L1)

- **Four subagent roles** under `plugin/agents/`, each with a narrowed toolset and an
  explicit, parseable return contract:
  - `reviewer` — critiques a diff or design artifact in isolation; returns an
    `approve`/`changes` verdict plus structured findings (`Read, Grep, Glob, Bash(git diff:*)`).
  - `grader` — grades outputs against assertions and emits `grading.json`
    (`text`/`passed`/`evidence` + summary); never edits the work (`Read, Grep, Glob`).
  - `implementer` — implements a scoped change in a worktree and reports files/tests/summary
    (`Read, Write, Edit, Bash, Grep, Glob`).
  - `architect` — produces a tech-design artifact + ADRs from requirements; docs only
    (`Read, Grep, Glob, Write`).
- **Agent eval contracts** at `plugin/agents/evals/<name>.evals.json` (`component.type:
  agent`, `tier2_quality` thresholds at `min_pass_rate 0.8`, `runs 5`), authored before the
  role bodies per the skill-factory order.
- **Handoff helper** `plugin/lib/agentic_forge/handoff.py` — loads SDLC handoff artifacts
  (Markdown + YAML frontmatter) and validates the header against per-type JSON Schemas
  (`research-brief`, `prd`, `tech-design`, `plan`, `review`), reusing `frontmatter.py`.
  Exposes `load_artifact` / `parse_artifact` (raise `HandoffError`), `validate_header`,
  `schema_for`, and the `status` / `verdict` / `severity` vocabularies. Unit-tested at 100%
  (`tests/test_handoff.py`).
- **Pattern references** under `plugin/patterns/` for Stage 2 skills to consume on demand:
  `handoff.md` (file-based handoff), `review-loop.md` (bounded N=3 writer→reviewer→revise),
  and `worktree.md` (git worktree isolation for the implementer).
- **ADR 0010** recording the handoff header-schema rules and the pattern-reference location.

### Added — agent Tier-2 eval harness

- **Agent eval runner** `plugin/lib/agentic_forge/agent_eval.py` + CLI
  `dev/run_agent_evals.py`: runs each engine role on its fixtures, grades with the `grader`
  role, aggregates with `benchmark.summarize`, and gates with `gate.tier2_quality` (the same
  gate as skills). The model/agent call is a seam with a `claude` runner (headless `claude
  -p`, level-2, authenticated via your **Claude subscription** through the CLI — recommended)
  and an `api` runner (Anthropic Messages, level-1, per-token), plus a `dry` mode that
  verifies wiring with no credentials. Roles can run isolated per case (`--isolate`, a fresh
  temp workdir each); the grader runs with read-only tools to verify on-disk artifacts.
  Unit-tested at 100% via stub seams.
- **Eval fixtures** `plugin/eval/fixtures/<role>/` (diffs, a `tech-design.md`, gradable
  outputs, a buggy parser + failing test, a PRD, decision/constraint briefs); each role
  contract's `files` now references them so the cases are runnable.
- **CI**: `eval.yml` now runs the agent Tier-2 — a dry-run wiring check on every eval job and
  the real `--runner claude` run on a Claude subscription (`CLAUDE_CODE_OAUTH_TOKEN`) when the
  secret is present. It installs the `claude` CLI and deliberately does not set
  `ANTHROPIC_API_KEY` (which would take precedence over the subscription token).
- **Packaging**: optional `eval` extra (`anthropic`, only for the `--runner api` path) so
  Tier-0 stays dependency-light, plus a mypy override so the absent SDK does not fail
  type-checking.
- **Docs**: `docs/eval-runbook.md` (how to run, fidelity levels, recording results) and
  **ADR 0011** (dedicated agent runner; narrows ADR 0009's "reuse skill-creator" for agents).

### Verified — agent Tier-2 results (2026-06-20)

Tier-2 (LLM-judged quality) run of the four engine roles via `--runner claude` on a Claude
subscription (Opus 4.8, `claude-opus-4-8`). Roles run at level-2 in fresh per-case temp
workdirs (`--isolate`) for independent measurement; the grader judges with read-only tools so
it can verify the real on-disk artifacts without modifying them. Assertions were strengthened
from the initial "floor" set to discriminating/negative checks (e.g. reviewer must catch the
negative-index silent-wrap, not only IndexError; grader must fail a partly-met assertion and
name the missing piece; implementer's retry must be bounded; architect's ADR must record a
genuinely rejected alternative). Gate: `min_pass_rate 0.8`, `runs 5`.

| Role | mean | stddev | lower_bound | n | Gate |
| --- | --- | --- | --- | --- | --- |
| reviewer | 1.000 | 0.000 | 1.000 | 5 | PASS |
| grader | 0.954 | 0.069 | 0.885 | 5 | PASS |
| implementer | 1.000 | 0.000 | 1.000 | 5 | PASS |
| architect | 1.000 | 0.000 | 1.000 | 5 | PASS |

All four pass. The gate is discriminating, not a rubber stamp: `grader` shows real
run-to-run variance (0.954, lower bound 0.885) and an adversarial probe scored a deliberately
weak reviewer output at 0.4. Harness hardening done during this run: strict boolean
pass-counting (a string `"false"` can no longer inflate); `--isolate` per-case workdirs;
read-only file-aware grading with a raised turn budget (the earlier architect failures were
the grader hitting `max-turns`, **not** a rate limit); retries/backoff and stdout+stderr
surfacing on a failed call.

### Added — deep-review skill (adversarial review)

- **`deep-review` skill** `plugin/skills/deep-review/` — a general, adversarial fan-out review
  for any target (docs, design/architecture, a code diff/PR, or the working tree): decompose
  into target-appropriate lenses, fan out independent reviewers, **verify each finding against
  the source**, and synthesize one deduplicated, prioritized report with fixes (optionally
  apply + re-gate). Router `SKILL.md` + `references/lenses.md` (lens catalog) + an evals-first
  contract (Tier-1 triggers, Tier-2 thresholds) with planted-defect fixtures under
  `plugin/eval/fixtures/deep-review/` (catch-rate + false-positive controls).
- **Pattern** `plugin/patterns/adversarial-review.md` — the reusable method
  (decompose → fan-out → verify → dedupe → synthesize → optional apply + re-gate); composes
  with the `reviewer` role, the review loop, and handoff, and mirrors `deep-research`'s
  harness. Stage 2 `code-review` can delegate to it.
- Systematizes the multi-agent review process used in this session so it is repeatable.
- **Gated (2026-06-20, Opus 4.8 via subscription):** Tier-0 green; **Tier-1** recall 1.000 /
  specificity 1.000 — after sharpening the description, which the trigger eval caught
  over-firing on a quick one-line lint (now routed to `code-review`); **Tier-2** mean 0.969,
  stddev 0.042, lower bound 0.927 (n=5) on the planted-defect fixtures (catches the planted
  contradiction/gap/bug/risk with no false positives on clean zones).

### Changed — Tier-3 E2E runner extended to the full six-phase spine

- `spine_e2e` now runs the whole spine — `research → product → architecture → plan → develop →
  code-review` — on an isolated taskstore copy, **starting from `FEATURE_REQUEST.md`** (no
  seeding: each phase produces the handoff the next consumes), with per-phase checkpoints (each
  artifact validates against its schema; develop's code passes the repo suite; review has a
  verdict). `prepare_workspace` gains an optional `seed` for partial runs. 100% unit-tested
  (correct-output stub + real git/pytest); dry-run clean.

### Added — Stage 2 spine (step 5c: plan phase — spine complete)

- **`plan` workflow skill** `plugin/skills/plan/` — the planning phase: turn `tech-design.md`
  into a dependency-ordered work plan (tasks with `deps`, checkpoints, deferred), delegating
  sequencing to the built-in `Plan` agent, and write a `plan.md` handoff for `develop`.
  **Tier-0 + Tier-1 recall 1.000 / specificity 1.000** (majority-of-3). Quality via the plan
  schema + the Plan agent.
- **The six-phase SDLC spine is now built**: `research → product → architecture → plan →
  develop → code-review`, each a gated workflow skill (Tier-0 + Tier-1 ≥ 0.9), joined by
  schema-validated handoff artifacts. The thin slice (architecture→develop→code-review) is
  proven end-to-end (Tier-3); the full six-phase E2E and the by-stack multi-language mechanism
  remain.

### Added — Stage 2 spine (step 5b: product phase)

- **`product` workflow skill** `plugin/skills/product/` — the product phase: turn
  `research-brief.md` into a PRD — assess the current product, define goals/non-goals/metrics/
  acceptance and user stories, and produce a `prd.md` handoff for `architecture`, eliciting
  ambiguities from the user rather than inventing them. **Tier-0 + Tier-1 recall 1.000 /
  specificity 1.000** (majority-of-3; clean separation of *what & why* (product) from *what
  exists* (research) and *how* (architecture)). Adds a schema-validated `research-brief.md`
  fixture (product's input). Quality via the prd schema + traceability to the brief.

### Added — Stage 2 spine (step 5a: research phase)

- **`research` workflow skill** `plugin/skills/research/` — the first spine phase: investigate a
  feature before it is specified by fanning out research tracks (delegating codebase exploration
  to the built-in `Explore` and external research to `deep-research`), synthesizing, and
  producing a `research-brief.md` handoff (cited sources + recommendation) that feeds `product`.
  **Tier-0 + Tier-1 recall 1.000 / specificity 1.000** (majority-of-3 router sim; distinct from
  `deep-research` (standalone report) and the spine neighbours after sharpening the description
  to own "compare/recommend before spec or design"). Depth quality comes from the delegated
  `deep-research` + the brief schema.

### Fixed — eval-gate + runner hardening (deep-review pass)

A deep multi-agent review of the whole codebase found real defects in the eval gates/runner;
all fixed with tests (lib coverage ~99%):

- **Gate integrity (`agent_eval`):** `grade_output` capped `passed` at the assertion count and
  `run_role` now aggregates over **expected assertion counts** (grade_output summaries), not
  `len(grader results)` — a grader returning extra/duplicate results can no longer push
  `pass_rate > 1.0` (inflating Tier-2), and omitted results now count as failures instead of
  vanishing. `runs <= 0` is rejected (was silently coerced to the default / produced empty runs).
- **Tier-0 false positive (`validation`):** markdown links with a `#anchor`/`?query` are
  stripped before the existence check (anchored reference links no longer fail the always-on
  gate). **New Tier-0 check:** every eval-case `files` fixture must exist (skill + agent
  contracts) — referenced fixtures can no longer silently rot.
- **Robustness:** `benchmark.pass_rate_of` tolerates a null `pass_rate` and an explicit
  `total: 0` (no crash / no silent drop); `spine_e2e.prepare_workspace` can re-run against the
  same `--workspace`; `check_wiring` flags duplicate fixture basenames (which the
  basename-flattening would otherwise overwrite silently).
- **Test gaps closed:** added `tests/test_dev_cli.py` (the `dev/` entry points + the
  unknown-runner `ValueError`) and regression tests for every fix above.

### Changed — documentation currency (deep-review pass)

The same review found docs that lagged the built code; brought them current:

- **Layer status:** `overview.md`, `README.md`, and `docs/README.md` now describe L1 and L2 as
  **built** (six roles; fan-out-fan-in / multi-aspect-review / adversarial-review / review-loop /
  worktree patterns; the six-phase spine proven end-to-end via Tier-3) instead of "planned" /
  "thin router skills (pre-implementation)".
- **Phase-workflows, not routers:** `CLAUDE.md` and `overview.md` describe L2 as a
  phase-workflow per SDLC phase (fan out → synthesize a handoff artifact), replacing the older
  "one router skill per domain, depth via sub-skills" framing.
- **Handoff producers:** `patterns/handoff.md` maps artifacts to the real skill names
  (`research`/`product`/`architecture`/`plan`), and documents `status` as recommended-but-not-
  enforced (the schema accepts any non-empty string), matching the relaxed handoff schema.
- **Ralph claim dropped:** removed "Ralph loops run natively" and the `ralph` keyword from
  `plugin.json` (and the README) — Ralph is not shipped/used yet.
- **Roster + runbook:** `eval-runbook.md` covers all six roles (adds `security-engineer`,
  `qa-engineer`) and the write-role fidelity note includes `qa-engineer`; `engine.md` keeps its
  Stage-1 scope but forward-points to the two Stage-2 specialists. Spine E2E docstrings now say
  "all six phases" instead of the old three-phase thin slice.

### Fixed — skill/pattern coherence (deep-review pass)

- **`code-review` can run the tools it requires.** Its `allowed-tools` widened from
  `Bash(git diff:*)` to `Bash`: the skill's style/lint aspect and its Verify step run the
  project's real tools (ruff/mypy/eslint/pytest/…), which the `git diff`-only grant forbade.
  Now consistent with `develop` and `deep-review`, and ready for multi-stack toolchains.
- **Canonical finding shape is consistent.** Added the missing `issue` field to the structured
  finding shape in `deep-review/SKILL.md`, `patterns/adversarial-review.md`, and
  `deep-review/references/lenses.md` (`severity, location, issue, evidence, suggested fix`),
  matching `code-review` and `patterns/handoff.md`.
- **No Tier-2 gate theater.** Documented in the eval-runbook that the agent eval CLI gates
  *roles* only; the `tier2_quality` thresholds declared by `deep-review`/`engineering-standards`/
  `skill-factory` are readiness contracts run via the harness / manual LLM-judge (an automated
  skill-Tier-2 CLI is a roadmap item), not gates this CLI enforces.

### Fixed — L4 guardrails (ADR 0019), step 4: security-review hardening

Independent security review of L4 (no blockers; `guardrails.py` 100%, all hooks fail-open
verified). Closed every finding:

- **Secret redaction (M1):** `redact_secrets` now catches `AWS_SECRET_ACCESS_KEY=` / `access_key=`
  (underscore-joined — no word boundary), PEM private-key blocks, and any `Authorization:` scheme
  — not just `Bearer`/`sk-`/`ghp_` (these get written to the audit log on disk).
- **mkfs false-positive (M2):** the disk-format block now requires a `/dev/` device argument
  (command-bounded), so `git grep mkfs` / `echo "…mkfs…"` are no longer wrongly blocked.
- **rm targets (M3):** also blocks `rm -rf` of system dirs (`/usr`, `/etc`, …), `~/`, and quoted
  `"/"`; still allows `rm -rf ./build`, `/tmp/x`, `~/Downloads/…`.
- **Force-push (M4/M5):** detects the `+refspec` form (`git push origin +main`) and matches a
  protected branch as a standalone token (no longer over-blocks `release-2024` / `feature/main-fix`).
- **Over-trigger + bounds (M6/N1/N2):** the test-gate triggers only on command-position
  `git commit`/`push` (not a quoted mention); `audit_record` bounds `tool`/`session_id`; the
  raw-disk block also covers `>|` clobber and `/dev/mapper/`. Plus hook `main()` allow-path tests
  (N3). `guardrails.py` stays 100% line+branch.

### Added — L4 guardrails (ADR 0019), step 3: docs + layer complete

- **`docs/architecture/guardrails.md`** — the L4 architecture doc (the four hooks, design notes,
  eval model, scheduling out-of-scope).
- Status across docs: overview L4, roadmap Stage 7, README, and the docs index now mark L4
  **Built**; `meta-core.md` lists `guardrails.py` + the guardrail hooks; `CLAUDE.md`'s layout
  notes them. Scope reconciled: **L4 = the four guardrail hooks; scheduling/observability is
  deferred** (a Stage-7 follow-on). **All five layers L0–L4 are now built.**

### Added — L4 guardrails (ADR 0019), step 2: the four hook scripts

The plugin gains runtime enforcement on tool use (reusing the `plugin/hooks/` pattern from L3):

- **`security.py`** (PreToolUse/Bash) — blocks dangerous commands (exit 2), allows the rest.
- **`commit_gate.py`** (PreToolUse/Bash) — on `git commit`/`git push`, runs the fast gate
  (`dev/validate.py` or the detected stack's lint) and blocks on failure; skippable via
  `AGENTIC_FORGE_SKIP_TEST_GATE`; fails open on infra errors.
- **`budget.py`** (PreToolUse/Task) — per-session subagent counter; warns over the soft cap,
  blocks over the hard (`AGENTIC_FORGE_SUBAGENT_SOFT` / `_HARD`).
- **`audit_log.py`** (PostToolUse) — appends a redacted JSONL audit line under
  `<project>/.agentic-forge/`; never blocks.
- `hooks.json` registers them (PreToolUse Bash → security + commit_gate, Task → budget;
  PostToolUse → audit) alongside the SessionStart hook. Each script is thin glue over
  `guardrails.py`, fails **open** on its own error (except the intentional security/gate blocks),
  and is unit-tested on allow + block paths (`tests/test_guardrail_hooks.py`). The gate file is
  `commit_gate.py` (not `test_gate.py`) to avoid pytest's `test_` collection prefix.

### Added — L4 guardrails (ADR 0019), step 1: guardrails lib

L4 (the last layer) begins — deterministic guardrail logic the hook scripts call.

- **`plugin/lib/agentic_forge/guardrails.py`** — `classify_command` (security deny-list: blocks
  `rm -rf /`/`~`, fork bombs, `curl|sh`, `mkfs`/`dd` to a device, `chmod 777 /`, raw-disk writes,
  and force-push to a protected branch — conservative, allows everything else), `is_commit_or_push`
  + `choose_gate` (test-gate: `dev/validate.py` if present, else the detected stack's lint),
  `redact_secrets` + `audit_record` (logging), and `bump_and_check` (subagent budget: warn over a
  soft cap, block over a hard cap). 100% line+branch coverage.
- `tests/test_guardrails.py` — allow **and** block paths for every guardrail.

### Fixed — doc/plan drift (pre-L4 audit)

An independent doc + plan audit before building L4 found drift (no blockers); fixed:
- **Layer/Stage mapping** (`docs/README.md` glossary): corrected the false "1:1" claim — L0–L3
  align with Stages 0–3, but **L4 = Stage 7**, and Stages 4–6 are SDLC-domain build-outs on top
  of L1–L3 (no new layer).
- **No untrue surface claims** (`plugin.json` keywords + `plugin.json` / `marketplace.json`
  descriptions): dropped `ui-ux` / `qa` / `deployment` (unbuilt) and the UI/UX/QA/deployment
  enumeration; added the knowledge base and `code-review`.
- **Counts current:** the on-listing router set is **nine** (was "eight") in the roadmap + the
  runner test comment; the eval-runbook tier2 list now includes `knowledge` (13, runs directly).
- **Stale "Layer 3 next":** spine.md and the roadmap now point only to Layer 4 (L3 shipped).
- **ADR index:** 0013 status "Accepted (design)" → "Accepted" (the spine is built). Immutable ADR
  bodies (0016 "eight" / 0017 "twelve") left as point-in-time records.

### Fixed — L3 knowledge base (ADR 0018), step 5: review hardening

Independent adversarial review of L3 (gate green, vault 100%, hook never blocks the session). One
**major** fixed: `add_note(moc=<themed>)` created a themed MOC but never linked it from the root
MOC, so the themed MOC was an immediate **orphan** — yet the `knowledge` capture workflow (and
eval id 2) require a clean vault. `add_note` now links a new themed MOC from the root
(idempotently) via extracted `_ensure_moc` / `_append_link` helpers, so a clustered capture stays
valid. Also: the masking test now asserts `validate_vault == []` (+ a two-notes-one-themed-MOC
case); `_WIKILINK` excludes newlines (a stray `[[` can't swallow text across lines). vault.py
stays 100% line+branch.

### Added — L3 knowledge base (ADR 0018), step 4: docs + layer complete

- **`docs/architecture/knowledge.md`** — the L3 architecture doc (vault format, deterministic
  core, recall/capture skill, session-start hook, eval model).
- Status across docs: `overview.md` L3, roadmap Stage 3, `README`, and the docs index now mark
  L3 **Built**; `meta-core.md` lists `vault.py` + `plugin/hooks/`; `CLAUDE.md`'s layout notes the
  session-start hook is built. **Only L4 (guardrails/observability) remains.**

### Added — L3 knowledge base (ADR 0018), step 3: session-start hook

The plugin's **first hook** — session-start knowledge injection.

- **`plugin/hooks/hooks.json`** — a `SessionStart` command hook (auto-discovered at the plugin
  root) running `${CLAUDE_PLUGIN_ROOT}/hooks/scripts/session_start.py` (15s timeout).
- **`plugin/hooks/scripts/session_start.py`** — reads the hook payload (`cwd`), builds the vault
  map via `vault.session_summary`, and emits it as SessionStart `additionalContext`. A **no-op**
  when there's no vault, and it **never blocks the session** (any error exits 0 silently). All
  logic is in the tested `vault.py`; the hook is thin glue.
- **`tests/test_session_start_hook.py`** — build_context (vault / no-vault), main (emits the
  injection JSON; no-vault → no output; bad stdin → safe exit 0), and hooks.json validity. mypy
  now type-checks `plugin/hooks` too (CI + README).

### Added — L3 knowledge base (ADR 0018), step 2: knowledge skill

- **`plugin/skills/knowledge/`** — an on-listing **recall + capture** skill. *Recall:* detect the
  vault, rank candidates via `vault.recall`, answer grounded in real notes citing `[[links]]` (or
  say the vault is silent — never invent). *Capture:* distill to atomic notes, `vault.add_note`
  (writes + wikilinks from a MOC), validate. Distinct from `research` (external) by design — it
  reads **our** notes. allowed-tools Read/Grep/Glob/Bash/Write/Edit; body 43 lines.
- **`evals/evals.json`** — Tier-1 triggers (recall + capture vs the neighbours, incl. the
  research boundary) + a Tier-2 contract (two capture cases: atomic, wikilinked, valid vault),
  run by `run_skill_evals.py`. The on-listing router set is now **9**, the tier2 skill set **13**.

### Added — L3 knowledge base (ADR 0018), step 1: vault lib

L3 begins — an Obsidian-format knowledge vault the plugin deploys + maintains in the target
repo's `docs/knowledge/`.

- **`plugin/lib/agentic_forge/vault.py`** — the deterministic core: parse/resolve `[[wikilinks]]`,
  load the note graph, **validate** (broken links, orphans, missing root MOC), **scaffold** an
  empty vault (root `MOC.md` + README), **add+link** an atomic note (creates the MOC if needed),
  **rank recall candidates** by token/tag/title overlap, and build the **session-start summary**
  (root MOC + highest-degree notes; `""` when there's no vault). Tolerates frontmatter-less notes
  and skips the vault README. 100% line+branch coverage.
- `tests/test_vault.py` — links/graph/validate/scaffold/add_note/recall/summary paths.

### Fixed — integrity audit (post-interruption review)

A full integrity audit — prompted by several interrupted background tasks (API rate-limits killed
some review agents mid-run) — confirmed the session's work is complete and consistent (277 tests,
clean tree, lib coverage 99%, and all prior review-fixes verified present in their files). It
found **two minor gaps**, both fixed:

- **`meta-core.md` was stale:** the two lib modules added this session (`tier1_runner.py`,
  `skill_eval.py`) and their CLIs (`run_tier1_evals.py`, `run_skill_evals.py`) were missing from
  the shared-library tree/table and the `dev/` line — ADR 0016/0017 had updated
  spine/roadmap/eval-runbook but not meta-core. Added (and noted `agent_eval.run_eval_cases` as
  the shared eval core).
- **Tier-3 was unwired in CI:** `run_spine_e2e.py` was the only eval runner not invoked in
  `eval.yml`; added a dry-run wiring step plus a cost-gated subscription E2E step, so all five
  runners now run in CI (Tier-0 always; Tier 1/2/3 cost-gated).

### Added — automated skill Tier-2 quality runner (ADR 0017)

The last manual tier is now automated — **every tier of the eval pyramid has a runner**.

- **`plugin/lib/agentic_forge/skill_eval.py`** — runs Tier-2 for the twelve skills that declare
  `tier2_quality` (`deep-review`, `skill-factory`, `engineering-standards`, the nine `*-patterns`
  packs). Two execution modes: **knowledge skills** (`engineering-standards`, `*-patterns`) run
  *as the `software-engineer` with them loaded* (system = SE body + standards + pack), the
  engineer's tools, isolated, graded against the skill's own assertions — making the long-claimed
  "exercised through the software-engineer's Tier-2" real; **on-listing skills** (`deep-review`,
  `skill-factory`) run directly. Graded by the `grader` role, aggregated, gated `mean − σ ≥ 0.8`.
  100% line + branch coverage.
- **`agent_eval` refactor:** the per-run loop (grading, the pass-rate cap, write-isolation,
  aggregate-over-expected-counts) extracted into `run_eval_cases`, shared by `run_role` and
  `run_skill` — one eval core, no drift; `run_role`'s external behaviour and `RoleReport`
  unchanged (its tests still pass).
- **`dev/run_skill_evals.py`** — CLI mirroring the others (`--runner dry|claude|api`, `--skill`,
  `--model`, `--runs`); `dry` checks every skill's wiring with no auth. It is the most expensive
  eval (a full software-engineer coding session per case × N), so CI cost-gates it.
- **CI:** `eval.yml` gains a real dry + cost-gated skill-Tier-2 step (replacing the manual note).
- **Docs:** ADR 0017 (+ index); the eval-runbook scope note is rewritten (the "no automated
  path" gap is closed) with a "Skill Tier-2" section; spine.md and roadmap mark all four tiers
  automated. Resolves the deep-review completeness finding that the packs' `tier2_quality` had no
  execution path.

### Added — Tier-1 trigger runner on live skill descriptions (ADR 0016)

Skill Tier-1 is now automated (it was a CI TODO no-op and an ad-hoc "router sim"):

- **`plugin/lib/agentic_forge/tier1_runner.py`** — builds the **live** always-on listing (every
  model-invocable skill's `name` + `description`; off-listing `*-patterns` /
  `engineering-standards` excluded) and classifies each on-listing router skill's trigger prompts
  against it. Grading is **deterministic** (a `should_trigger` prompt must select the skill =
  recall; a `should_not_trigger` must not = specificity), sampled **majority-of-N**, gated ≥ 0.9
  through the shared `gate.trigger_metrics` + `gate.tier1_trigger` — giving those previously
  test-only pure functions a production caller. Reuses the `agent_eval` transport seam (tools
  off, one turn); no second transport. 100% line + branch coverage.
- **`dev/run_tier1_evals.py`** — CLI mirroring `run_agent_evals` (`--runner dry|claude|api`,
  `--skill`, `--model`, `--runs`); `dry` verifies the listing/trigger wiring with no auth.
- **CI:** `eval.yml`'s skill-Tier-1/2 TODO step is replaced by a real dry + cost-gated
  subscription Tier-1 run; skill Tier-2 stays a documented manual step.
- **Docs:** ADR 0016 (+ index); an eval-runbook "Skill Tier-1" section; spine.md and roadmap mark
  the live runner built (replacing the router-sim wording). Scope: the eight on-listing router
  skills (research/product/architecture/plan/develop/code-review/deep-review/skill-factory);
  off-listing packs are Tier-1-exempt by design.
- **Independently adversarial-reviewed** (no blockers; the gate's grading semantics, listing
  fidelity, and wiring verified correct; 100% line+branch). Applied its findings: `check_wiring`
  now flags a `tier1_trigger` block missing a recall/specificity value (a `{}` threshold would
  otherwise pass vacuously — recall 0 yet PASS), and `run_tier1` refuses a mis-wired plugin
  (defense-in-depth, not only the dry CLI); docstrings note the terse-answer-format assumption
  and odd-`runs`; the CLI warns on an unknown `--skill`.

### Changed — deep-review pass (docs currency + completeness audit)

A four-reviewer deep review (docs / lib+gates / skills / completeness). Three lost their final
synthesis to a transient API rate-limit, so docs/lib/skills were re-reviewed inline; the
completeness + eval-pyramid audit completed — **no blockers/majors**, and it independently
verified Tier-0 and agent-Tier-2 are real (272 tests, lib coverage 99%). Applied its findings:

- **Doc currency:** `spine.md` status corrected from "Designed (pre-implementation)" to **Built**
  (it contradicted its own body); `README` status + checklist now state multi-stack/by-stack is
  built (nine packs), not "next"; `overview.md` L2 notes the spine is stack-parametric;
  `engine.md`'s "fan-out/fan-in deferred" line clarified (the *pattern* shipped in Stage 2 — only
  research-at-scale and Ralph remain deferred).
- **No overstated coverage:** the eval-runbook now states plainly that the `*-patterns` /
  `engineering-standards` `tier2_quality` thresholds have **no automated execution path yet** (the
  `software-engineer` eval cases don't exercise pack idioms) — meet them via a manual judge until
  pack-aware SE cases land; that wiring is the named roadmap item.
- **Honesty in code/schema:** `spine_e2e.py`'s docstring now notes the Python toolchain is
  hardcoded for the fixture (a non-Python E2E would drive the command from
  `stacks.primary(repo).toolchain.test`); `evals.schema.json` marks the unused `tier3_e2e` and
  the extra `component.type` enum values as **reserved** for future component types.

### Added — by-stack: javascript / jvm / dotnet / ruby / php packs (pack coverage complete)

Five more `*-patterns` reference packs (off-listing, `disable-model-invocation`), completing pack
coverage for **every registered stack**:

- **`javascript-patterns`** — plain JS/Node: ESM, `const`/`let`, awaited async, `===`,
  boundary validation, JSDoc + `// @ts-check`; pitfalls (floating promises, `==`/coercion, `var`
  hoisting, prototype pollution).
- **`jvm-patterns`** — Java/Kotlin: the Gradle/Maven wrapper, JUnit 5, `Optional`/null-safety,
  records/data classes, try-with-resources/`use`; pitfalls (NPE, `==` vs `.equals`,
  thread-safety, swallowed exceptions).
- **`dotnet-patterns`** — C#: `dotnet build`/`test`/`format`, nullable reference types,
  async-all-the-way (no `.Result`/`.Wait()`), records/pattern matching, `IDisposable`/`using`;
  pitfalls (`async void`, blocking-on-async deadlock, multiple enumeration).
- **`ruby-patterns`** — Bundler/RSpec/RuboCop, Enumerable/guard clauses/`&.`, specific error
  classes, `frozen_string_literal`; pitfalls (bare `rescue`, monkey-patching, `nil`, N+1).
- **`php-patterns`** — Composer/PHPUnit/PHPStan, `declare(strict_types=1)` + typed signatures,
  PSR-12/PSR-4, prepared statements; pitfalls (SQL injection, loose `==`, unvalidated
  superglobals).
- **Registry + tests:** each `STACKS` entry now carries its pack; `test_shipped_packs` covers all
  nine and `test_profile_carries_pack` is parametrized over every stack. The no-pack
  `format_profile` case is now the `unknown` profile (every *registered* stack ships a pack;
  detection-only stacks remain allowed by design).
- **Docs:** spine.md and roadmap mark by-stack pack coverage complete; the
  `engineering-standards`-only fallback now applies to unrecognized (`unknown`) repos.
- Each pack ships a 2-case `tier2_quality` readiness contract (no `tier1_trigger`); bodies
  51–55 lines; full Tier-0 green; `stacks.py` stays 100% line+branch.
- **Independently adversarial-reviewed** — jvm/dotnet/php by language-expert agents,
  javascript/ruby inline; **no blockers/majors**. Applied their polish: jvm table uses the
  `./mvnw` wrapper for symmetry with `./gradlew` (+ a `stacks.py` note that JVM has no canonical
  formatter default); dotnet adds the `ConfigureAwait(false)` rationale and `await using` /
  `IAsyncDisposable` coverage (+ eval), and gives `async void` its consequence; php states
  `declare(strict_types=1)` must be the *first statement*, tags the modern features as 8.0–8.1,
  and adds the "never silence a checker" line for parity.

### Added — by-stack: rust-patterns (fourth stack pack)

- **`plugin/skills/rust-patterns/`** — the fourth `*-patterns` reference pack (off-listing,
  `disable-model-invocation`), modelled on the prior packs: the Cargo toolchain (prefer the
  repo's Makefile/justfile/CI; `cargo test`, `cargo check`/`build`, `cargo clippy -- -D warnings`,
  `cargo fmt` defaults), idioms (borrow over clone, `&str`/`&[T]` params; `Result` + `?` with
  `thiserror`/`anyhow`; `Option` over sentinels; make illegal states unrepresentable; iterators;
  fearless concurrency via `Send`/`Sync` + `Arc<Mutex<…>>`), testing (`#[cfg(test)]` units,
  `tests/` integration, doc-tests, `Err`/boundary cases), and high-value pitfalls (`unwrap`/
  `expect` panics, `.clone()` to dodge the borrow checker, undocumented `unsafe`, blocking in
  async / lock held across `.await`, integer overflow debug-vs-release, `Rc`/`RefCell` cycles).
- **Registry wiring:** `stacks.STACKS["rust"].pack = "rust-patterns"`; extended
  `test_shipped_packs`, parametrized the end-to-end pack assertion over python/typescript/go/rust,
  and re-pointed the no-pack format test at a still-packless stack (ruby). No workflow-skill
  change needed.
- **`evals/evals.json`** — `tier2_quality` readiness contract (no `tier1_trigger`), exercised
  through the `software-engineer`'s Tier-2. Body 65 lines; Tier-0 green.
- **Docs:** spine.md and roadmap mark python/typescript/go/rust packs shipped (further packs
  incremental).
- **Independently adversarial-reviewed** (deep Rust-expertise agent; no blockers/majors, gate
  green) and refined from its findings: standardise clippy on `--all-targets -- -D warnings`
  across the prose/DoD/evals (so the lint gate also covers test code, matching the toolchain
  table); state integer-overflow as governed by `overflow-checks` (debug/test default) rather
  than an absolute debug-vs-release rule; name `Weak` as the fix for `Rc`/`RefCell` cycles.

### Added — by-stack: go-patterns (third stack pack)

- **`plugin/skills/go-patterns/`** — the third `*-patterns` reference pack (off-listing,
  `disable-model-invocation`), modelled on `python-patterns`/`typescript-patterns`: the Go
  toolchain (prefer the repo's Makefile/CI; `go test ./... -race`, `go vet`, `gofmt`/`goimports`,
  `golangci-lint` defaults; keep `go.mod` tidy), idioms (errors as values wrapped with `%w` +
  `errors.Is`/`As`, accept-interfaces/return-concrete, `defer` cleanup, `context.Context` first
  param, no goroutine leaks), testing (table-driven `t.Run` subtests, `-race`, determinism), and
  high-value pitfalls (unchecked errors, nil-interface-vs-nil-pointer, closed-channel send,
  `defer`-in-loop, loop-variable capture incl. the Go 1.22 change, unchecked type assertions,
  random map order).
- **Registry wiring:** `stacks.STACKS["go"].pack = "go-patterns"`; extended `test_shipped_packs`
  and added an end-to-end `go.mod` → `go-patterns` pack assertion. No workflow-skill change
  needed — `develop` / `code-review` / the roles pick it up via the profile.
- **`evals/evals.json`** — `tier2_quality` readiness contract (no `tier1_trigger`), exercised
  through the `software-engineer`'s Tier-2. Body 66 lines; Tier-0 green.
- **Docs:** spine.md and roadmap mark `python-patterns` + `typescript-patterns` + `go-patterns`
  shipped (further packs incremental).

### Added — by-stack: typescript-patterns (second stack pack)

- **`plugin/skills/typescript-patterns/`** — the second `*-patterns` reference pack (off-listing,
  `disable-model-invocation`), modelled on `python-patterns`: the TS toolchain (prefer the repo's
  `package.json` scripts and the package manager the lockfile implies — npm/pnpm/yarn/bun;
  `tsc --noEmit` / eslint / prettier defaults), strict-typing idioms (`strict` on, no `any`,
  `unknown` + narrowing, discriminated unions, `import type`, `satisfies`, union literals over
  `enum`), testing (the repo's runner, type-level tests, determinism, boundary + error cases),
  and high-value pitfalls (unsound `as` / non-null `!`, floating promises, `==` vs `===`, loose
  `tsconfig`, `enum` cost).
- **Registry wiring:** `stacks.STACKS["typescript"].pack = "typescript-patterns"`, so a
  `tsconfig.json` repo now routes to the pack; updated the registry-invariant test and added a
  TS `.pack` assertion. No workflow-skill change needed — `develop` / `code-review` / the roles
  pick it up generically via the profile.
- **`evals/evals.json`** — `tier2_quality` readiness contract (no `tier1_trigger`), exercised
  through the `software-engineer`'s Tier-2 like `python-patterns`. Body 64 lines; Tier-0 green.
- **Docs:** spine.md and roadmap mark `python-patterns` + `typescript-patterns` shipped (further
  packs incremental). Bare JavaScript (no `tsconfig.json`) stays detection-only for now.
- **Independently adversarial-reviewed** (deep TS-expertise agent; no blockers/majors, gate
  green) and refined from its findings: list both `bun.lock` (Bun ≥ 1.2's default text lockfile)
  and the legacy `bun.lockb`; add `prettier`-formatted to the Definition of done (parity with
  `python-patterns`).

### Changed — deep-review lens catalog enriched (from this session's reviews)

Per the "living catalog" rule, added three durable lenses to
`plugin/skills/deep-review/references/lenses.md` from failure modes surfaced this session:

- **Matcher precision** (under *Robustness at seams*) — a regex/config/hint parser that
  over-matches lookalikes (`stackoverflow` for a `stack` key) or bridges newlines (`\s` vs
  `[ \t]`); test the forms that should match and the near-misses that should not.
- **Branch-vs-line coverage honesty** (under *Tests & coverage*) — 100% line coverage can hide
  an uncovered branch (`--cov-branch`); don't claim coverage the run doesn't show.
- **Packaging / install boundary** (cross-cutting) — a shipped skill/agent must reference only
  what ships with it; a link that resolves in-repo but points outside the published root
  (`../../../docs/`) dangles once installed — cite by name instead.

### Fixed — by-stack (multi-language), step 5: adversarial-review hardening

An independent fresh-agent adversarial review of the whole by-stack feature found **no blockers
and no majors** (gate green); applied its actionable items:

- **Regex hardening (`stacks.py`):** a bare `stack:` no longer bridges a newline to capture the
  next line's token as the value — the delimiter-adjacent separators are now line-local
  (`[ \t*]`, not `\s`). Behaviour for the documented forms is unchanged.
- **Test strength (`tests/test_stacks.py`):** added parametrized positive hint-form cases
  (bullet, bold `**Stack:**`, blockquote, `=` delimiter, quoted value, indented, dotted alias)
  and negative cases (headings, `stackoverflow:`, newline/YAML-list values), plus a
  bogus-hint-in-`CLAUDE.md` → real-hint-in-`AGENTS.md` fall-through test — `stacks.py` is now at
  **100% line + branch** coverage.
- **Doc clarity:** `develop` now states the engineer **re-derives** the stack profile on the
  worktree (rather than implying a profile object is handed across); ADR 0015 + spine.md clarify
  that `tsconfig.json` alone detects TypeScript (suppressing a co-present bare `package.json`);
  `meta-core.md`'s shared-library tree/table now list `spine_e2e.py` + `stacks.py` and the
  `run_spine_e2e.py` CLI (closing pre-existing Stage-2 drift).

### Verified — by-stack (multi-language), step 4: detection closed on the E2E fixture

- **Fixture target-repo gains a `pyproject.toml`** (`plugin/eval/fixtures/spine/target-repo/`)
  so the SDLC-spine E2E target is a realistic Python project — and `stacks.detect` resolves it
  to `python` → `python-patterns` (previously, with no manifest, it fell back to `unknown`).
- **`tests/test_spine_e2e.py`** asserts the prepared workspace is detected as Python with the
  `python-patterns` pack, closing the by-stack loop on the real E2E target. The in-workspace
  `pytest` run stays green with the new manifest.
- **Docs:** roadmap marks the by-stack mechanism built (further `*-patterns` packs incremental);
  the eval-runbook scope note now lists the `*-patterns` packs among the skills that declare a
  `tier2_quality` readiness contract exercised through the role's Tier-2.

### Changed — by-stack (multi-language), step 3: spine consumes stack detection

The spine is now stack-parametric end to end — detection feeds the implement/review phases:

- **`develop`** detects the stack in step 1 (`stacks.primary`/`stacks.detect`), passes the
  profile to `software-engineer` (which loads the named `<stack>-patterns` pack, e.g.
  `python-patterns`, or falls back to standards + the profile's toolchain), and the review gate
  uses the stack's lint/type tools.
- **`code-review`** detects the stack in Scope so the style/lint aspect runs that stack's real
  tools (the profile's toolchain — ruff/mypy, eslint/tsc, go vet, …), preferring the repo's
  declared commands.
- **`software-engineer`** and **`qa-engineer`** roles now detect the stack deterministically
  (`stacks.detect`/`primary`) and load the `<stack>-patterns` pack — replacing the earlier
  prose "detect from CLAUDE.md/AGENTS.md/the repo" with the tested helper. Both prefer the
  repo's own declared commands over the profile defaults.

### Added — by-stack (multi-language), step 2: python-patterns pack

- **`plugin/skills/python-patterns/`** — the first stack reference pack: an off-listing
  (`disable-model-invocation: true`) knowledge skill, modelled on `engineering-standards`,
  carrying only Python-specific conventions on top of the standards — the toolchain (prefer the
  repo's declared commands; `pytest` / `ruff` / `mypy` defaults), idioms (typing, dataclasses,
  pathlib, EAFP, context managers), testing discipline (parametrize, fixtures, `tmp_path`,
  determinism, boundary + error cases), layout, and the high-value Python pitfalls (mutable
  defaults, bare `except`, late-binding closures, `is` vs `==`, secrets in logs).
- **`evals/evals.json`** — declares a `tier2_quality` readiness contract (no `tier1_trigger`;
  the pack is loaded on demand, not auto-triggered), exercised through the `software-engineer`'s
  Tier-2 like `engineering-standards`. Body 66 lines; passes Tier-0.

### Added — by-stack (multi-language), step 1: deterministic detection

The spine becomes stack-parametric (ADR 0015), starting with the detection layer:

- **`plugin/lib/agentic_forge/stacks.py`** — `detect(repo)` / `primary(repo)` identify a target
  repo's stack(s) from an explicit `stack:` hint (CLAUDE.md / AGENTS.md, with aliases) or
  manifest signatures (`pyproject.toml` → python, `tsconfig.json`/`package.json` →
  typescript/javascript, `go.mod` → go, `Cargo.toml` → rust, `*.csproj` → dotnet, …), ranked by
  specificity (TypeScript supersedes a bare `package.json`); an empty repo yields the `unknown`
  profile. A `StackProfile` carries `stack_id`, `display`, the `*-patterns` `pack` (or `None`),
  a conventional `toolchain` (test/lint/typecheck/format), and the manifest evidence;
  `format_profile` renders a one-line summary for workflows to log. The `STACKS` registry is
  data — adding a language is one entry.
- **`tests/test_stacks.py`** — manifest detection per stack, hint precedence + aliases +
  fall-through, TS/JS suppression, monorepo ranking, unknown, and registry invariants;
  `stacks.py` at 100% line + branch coverage, ruff + mypy clean.

### Verified — full six-phase spine E2E (Tier-3, 2026-06-21)

The real `--runner claude` scenario (Opus 4.8) carried `task-priorities` through **all six
phases** — `research → product → architecture → plan → develop → code-review` — on an isolated
taskstore copy, starting from `FEATURE_REQUEST.md`. **All six phases pass**: each produced a
schema-valid handoff the next consumed (`research-brief → prd → tech-design+ADRs → plan`),
`develop` implemented priorities with the repo suite green, and `code-review` approved. The
spine is proven end-to-end across its full length — idea to reviewed, tested code.

The run again caught real schema-vs-output mismatches (the value of Tier-3): the model used
`status: complete` (a reasonable lifecycle label outside our enum) and an unquoted `date:` that
YAML parsed into a date object — both rejected by the over-strict schema.

### Fixed — handoff schema: lenient status + date

- `lib/agentic_forge/handoff.py`: `status` now validates as any non-empty string (the
  `STATUSES` list stays as recommended-but-not-enforced guidance — real artifacts use labels
  like "complete"); the `date` field accepts a string or a YAML-parsed date. `verdict` and
  `severity` stay strict (the review loop branches on them). Tests added; coverage 100%.

### Verified — Stage 2 thin-slice E2E (Tier-3, 2026-06-21)

The real `--runner claude` scenario (Opus 4.8, subscription) carried `task-priorities` through
`architecture → develop → code-review` on an isolated taskstore copy. **All three phases pass**
their checkpoints: `architecture` produced a schema-valid `tech-design.md` + 2 ADRs;
`develop` implemented priorities with the repo's **pytest suite green**; `code-review` emitted a
valid `review.md` with an `approve` verdict. The thin slice is proven end-to-end — one
continuous path from a PRD to reviewed, tested code.

The run **caught a real bug** (the point of Tier-3): the architect produced *structured* list
entries (a decision as `{id, title, adr}`, a component as `{name, change}`, a risk as
`{risk, mitigation}`) — richer and more useful than bare strings — but the handoff `tech-design`
schema required arrays of strings, so the otherwise-correct artifact failed validation.

### Fixed — handoff schema accepts structured list entries

- `lib/agentic_forge/handoff.py`: list fields (`decisions`, `components`, `risks`, `goals`,
  `acceptance`, `non_goals`, `metrics`, `sources`, `checkpoints`, `deferred`) now accept entries
  that are **a string or a structured object**, matching how real artifacts are written. Bare
  strings still validate; tests added; `handoff` coverage stays 100%.

### Added — Stage 2 thin slice (step 4: Tier-3 E2E runner)

- **Tier-3 spine E2E runner** `plugin/lib/agentic_forge/spine_e2e.py` + CLI
  `dev/run_spine_e2e.py`: carries the `task-priorities` feature through
  `architecture → develop → code-review` on an **isolated copy** of the taskstore fixture repo
  (`git init`'d), checking per-phase checkpoints — tech-design + ADR validate against the
  handoff schemas, the implemented code carries a real priority marker and the repo's **test
  suite passes**, and `review.md` validates with a verdict. The model call is the same seam as
  the agent runner (`--runner dry` for wiring, `--runner claude` for the real run on the
  subscription). Unit-tested at 100% via a correct-output stub + real git/pytest; dry-run clean.
- **PRD fixture** `plugin/eval/fixtures/spine/prd.md` (task-priorities) — the `architecture`
  phase's input, schema-validated.

### Added — Stage 2 thin slice (step 3c: develop flagship workflow)

- **`develop` workflow skill** `plugin/skills/develop/` — the implementation phase / flagship:
  read `plan.md`+`tech-design.md`, set up a git worktree (single, sequential v1), implement the
  step via the `software-engineer` role, **gate it with a multi-aspect review** (develop
  produces the staged worktree diff and hands it to `reviewer`+`security-engineer`+lint),
  bounded loop-back (N=3, with a stated terminal state), then `qa-engineer` hardens the suite,
  and finally hand off + **remove the worktree**. **Tier-0 + Tier-1 recall 1.000 /
  specificity 1.000** (majority-of-3); end-to-end quality is the Tier-3 spine scenario.
- **Spine fixtures** `plugin/eval/fixtures/spine/{plan.md,tech-design.md}` (task-priorities),
  validated against the handoff schemas — develop's inputs (the thin slice skips the plan phase).
- **Flagship self-review caught real defects** (two adversarial reviewers), all fixed before
  commit: the review gate fed an **empty diff** (`BASE...HEAD` is empty for an uncommitted
  worktree → now stage + `diff --staged`, including new files); the reviewer couldn't read a
  worktree via `git -C` (now develop supplies the diff text); the flagship eval referenced a
  non-existent `plan.md`; **unbounded QA loop** and **missing N=3 terminal state**; **worktree
  cleanup** never invoked; and doc-currency drift (patterns/spine still described the deferred
  parallel-impl model and a per-skill Tier-2 that the slice delegates to roles + Tier-3).
- Reconciled the patterns (`worktree`, `multi-aspect-review`, `fan-out-fan-in`) and
  `spine.md`'s eval model to the single-worktree v1 + delegate-quality reality.

### Added — Stage 2 thin slice (step 3b: code-review workflow)

- **`code-review` workflow skill** `plugin/skills/code-review/` — the review phase: the
  [multi-aspect review](plugin/patterns/multi-aspect-review.md) pattern wired as a skill —
  fans out reviewers by aspect (correctness/reuse via `reviewer`, security via
  `security-engineer`, integration/API, style/lint via the real tools), verifies, aggregates
  into one approve/changes verdict (any blocker/major ⇒ changes), and writes a `review.md`
  handoff. Code is its target; docs/design and deep audits go to `deep-review` (per ADR 0013 /
  the user's split). **Tier-0 + Tier-1 recall 1.000 / specificity 1.000** (majority-of-3
  router sim — distinct from `deep-review`/`simplify` and the spine neighbours); review quality
  is the `reviewer`/`security-engineer` roles' Tier-2 (PASS).

### Added — Stage 2 thin slice (step 3a: architecture workflow)

- **`architecture` workflow skill** `plugin/skills/architecture/` — the `tech-design` phase:
  turns an approved PRD into `tech-design.md` + `adr-*.md` under `docs/sdlc/<feature>/`,
  weighing alternatives and tracing goals to components. Delegates the design to the
  `architect` role; owns the workflow + handoff validation. **Tier-0 + Tier-1
  recall 1.000 / specificity 1.000** (majority-of-3 router sim, non-overlapping vs
  product/plan/develop/research); design quality is the `architect` role's Tier-2 (PASS).
- **Review-lens enrichment** `plugin/skills/deep-review/references/lenses.md` — added dimensions
  surfaced by this session's self-reviews: eval/test-harness validity (fixtures run, isolation
  /no-leak, determinism, no degenerate-pass), robustness at seams (parsing external/LLM
  output), safety defaults (enforced vs opt-in), doc currency vs ADRs, and a "living catalog"
  rule (grow the lenses from new failure modes).
- **Tier-1 methodology**: sample each trigger prompt N times and take the majority (absorb
  router stochasticity), documented in the eval-loop guide.

### Added — Stage 2 thin slice (step 2: roles + standards)

- **Engine roles for the thin slice.** Renamed `implementer` → **`software-engineer`** (the
  base engineering role, language/framework-agnostic; loads the standards + stack skills by
  context — ADR 0014). Added two new gated quality roles: **`security-engineer`** (security
  lens of a review; read-only) and **`qa-engineer`** (designs/writes/runs tests; never weakens
  a test or edits implementation). Each ships an agent eval contract + planted-defect fixtures.
- **`engineering-standards` skill** `plugin/skills/engineering-standards/` — a lean,
  off-listing (`disable-model-invocation: true`) knowledge skill of the standards we apply in
  target repos; loaded by `software-engineer`, exercised through its Tier-2.
- **Eval-runner hardening** (`agent_eval`): write roles now **run in a forced per-case
  sandbox** — fixtures are materialized into a temp workdir by basename and prompts carry no
  repo-relative paths, so a write role can never reach or mutate the real repo. `parse_grading`
  is now robust to prose/code-fence wrapping and stray braces (balanced-brace extraction), with
  a one-shot grader retry. Both fixes came out of the step-2 self-review (see below). Unit
  tests at 100% coverage.
- **ADR 0014** — one `software-engineer` base role + stack skills (not per-stack agents);
  updates spine.md roster and the living docs (the `implementer` rename).

### Verified — Stage 2 thin-slice roles Tier-2 (2026-06-21)

Tier-2 on a Claude subscription (Opus 4.8), per-case sandbox isolation. All pass; isolation
verified leak-free by fixture checksum (unchanged before/after).

| Role | mean | stddev | lower_bound | n | Gate |
| --- | --- | --- | --- | --- | --- |
| software-engineer | 1.000 | 0.000 | 1.000 | 5 | PASS |
| security-engineer | 1.000 | 0.000 | 1.000 | 5 | PASS |
| qa-engineer | 1.000 | 0.000 | 1.000 | 5 | PASS |

**Self-review caught real defects** (two independent adversarial reviewers, per the
review-each-step discipline), all fixed before this result: a sandbox leak (a write role had
mutated a real fixture in an earlier run), two fixture bugs (a broken import and hyphenated
test files that bare `pytest` didn't discover), the opt-in isolation gap (now enforced for
write roles), a degenerate-pass security assertion, and the grader-JSON parse fragility.

### Added — Stage 2 thin slice (step 1: patterns + fixture)

- **Pattern references** `plugin/patterns/fan-out-fan-in.md` (partition → parallel subagents →
  synthesize; the backbone of phase-workflows) and `plugin/patterns/multi-aspect-review.md`
  (code review fanned out by aspect — correctness / security / integration+API / lint — into
  one verdict; the review gate inside `develop` and the engine of the `code-review` phase).
- **Fixture target-repo** `plugin/eval/fixtures/spine/target-repo/` — a small, real Python
  library (`taskstore`) with tests and a `FEATURE_REQUEST.md` (task priorities), the external
  target the SDLC-spine E2E scenario carries a feature through on an isolated copy.
- **Tooling:** ruff now excludes `plugin/eval/fixtures` (fixtures are test data, not source).
- `docs/architecture/overview.md`: fan-out/fan-in promoted from deferred to a built pattern.

### Added — Stage 2 design

- **SDLC spine design** `docs/architecture/spine.md` + **ADR 0013** (supersedes ADR 0012):
  the spine is a **chain of phase-workflows** — `research, product, architecture, plan,
  develop, code-review` — each a multi-stage skill that gathers inputs, **fans out subagents**
  by direction/component, synthesizes, and analyses; joined only by handoff artifacts.
  Fan-out/fan-in becomes a **core** pattern. Built **fresh** with the ancestor `ai-skills`
  repo as reference; an **expanded specialist agent roster** (stack engineers, architects,
  security/qa/…, each gated; supersedes ADR 0009's Stage-1 "no new roles"); phase-workflows
  are model-driven fan-out (SKILL.md procedure + `lib/` glue), not the harness Workflow tool;
  trigger taxonomy by owned artifact; E2E on a Python fixture target-repo; **thin slice
  `architecture → develop → code-review` first**, multi-language (by-stack) after.
  Pre-implementation. ADR 0012 (thin routers) retained as superseded.

### Added — handoff

- **`docs/handoff-to-cli.md`** — checklist and starter prompt for continuing implementation
  (Stage 1+) in the Claude Code CLI, where the plugin runs and the eval loop executes.

### Fixed — packaging

- **Editable install (`pip install -e .`)** failed with a setuptools flat-layout error
  ("Multiple top-level packages discovered: ['dev', 'plugin']"). Added `[build-system]` and
  `[tool.setuptools]` (`package-dir = {"" = "plugin/lib"}`, `packages = ["agentic_forge"]`)
  so only the real package is built.

### Changed / Fixed — documentation review

- **Overhead gating made real:** `benchmark.summarize` now computes token/time overhead
  deltas from optional `timing.json` input, which `gate.tier2_quality` already checks
  (previously the gate could never apply overhead budgets). Added tests.
- **Agents now gated like skills:** `validate_agent` requires a sibling eval contract at
  `plugin/agents/evals/<name>.evals.json` with `component.type: agent`; skill contracts must
  declare `component.type: skill`. Added tests for agents, the manifest, and validator
  branches.
- **Coverage enforced:** `pytest-cov` added; CI runs `--cov=agentic_forge --cov-fail-under=80`
  (coverage ~96% at that milestone). Aligned the coverage claim across `CLAUDE.md`, overview, and
  meta-core docs.
- **Reduced duplication:** the eval-pyramid definition is now canonical in
  `docs/architecture/overview.md`; `plugin/eval/README.md` points to it instead of restating.
- **Citation fix:** `skill-creator` references updated to the official
  `claude-plugins-official` plugin and install command.
- **Plan consistency:** roadmap Stage 1 design questions marked resolved (engine.md/ADR 0009);
  Stage 2 role set pinned to the four roles + built-in Explore/Plan; Stage 3 split into
  vault-infra (Stage 0+) vs write-path (needs Stage 2). README notes the KB is Layer 3.

### Notes

- Decision records for the choices above live in `docs/architecture/decisions/`.
- Gate status at this milestone: `validate` clean, `pytest` green, `ruff` clean,
  `mypy` clean; `skill-factory` and the four engine roles pass Tier-0 (coverage ~97.6%). The
  agent Tier-2 runner is in place — run it locally (`python dev/run_agent_evals.py`) or via
  `eval.yml` using a Claude subscription token (`CLAUDE_CODE_OAUTH_TOKEN`); see
  [docs/eval-runbook.md](docs/eval-runbook.md).
