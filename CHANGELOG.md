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

### Added — handoff

- **`docs/handoff-to-cli.md`** — checklist and starter prompt for continuing implementation
  (Stage 1+) in the Claude Code CLI, where the plugin runs and the eval loop executes.

### Changed / Fixed — documentation review

- **Overhead gating made real:** `benchmark.summarize` now computes token/time overhead
  deltas from optional `timing.json` input, which `gate.tier2_quality` already checks
  (previously the gate could never apply overhead budgets). Added tests.
- **Agents now gated like skills:** `validate_agent` requires a sibling eval contract at
  `plugin/agents/evals/<name>.evals.json` with `component.type: agent`; skill contracts must
  declare `component.type: skill`. Added tests for agents, the manifest, and validator
  branches.
- **Coverage enforced:** `pytest-cov` added; CI runs `--cov=agentic_forge --cov-fail-under=80`
  (current coverage ~96%). Aligned the coverage claim across `CLAUDE.md`, overview, and
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
  `mypy` clean; `skill-factory` passes its own Tier-0.
