# Changelog

All notable changes to agentic-forge are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow semantic
versioning once it has a public surface.

## [Unreleased]

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
