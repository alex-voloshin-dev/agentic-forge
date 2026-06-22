# agentic-forge

A skill-centric, eval-driven Claude Code plugin for the full software lifecycle.

This file is the project constitution. Every contributor (human or agent) MUST follow it.

## What this is

- A **Claude Code plugin only**. No multi-vendor packaging. We use Claude Code native
  primitives directly: skills, subagents, hooks, plan mode, git worktrees, review loops,
  Ralph loops, and headless runs.
- **Standard-compliant**: every skill conforms to the [Agent Skills](https://agentskills.io)
  open standard and passes `skills-ref validate`. Claude Code extensions live only in
  documented optional frontmatter fields.

## Core principles (non-negotiable)

1. **Skill-centric.** Skills are the primary unit and express *workflows*. Users do not
   call agents or commands by hand — skills auto-load by `name` + `description`. Agents are
   executors that skills delegate to (`context: fork` + `agent`); hooks are guardrails.

2. **Router discipline.** The skill listing has a hard context budget (~1% of the model
   window); descriptions of rarely used skills get dropped. So we keep a SMALL set of
   always-on entry/router skills with sharp descriptions, and push depth into `references/`
   (loaded on demand, so it never sits in the listing). Note: `user-invocable: false` does
   *not* save listing budget — it only hides a skill from the user's `/` menu while keeping
   it model-invocable with its description still in the listing; `disable-model-invocation:
   true` is what drops a skill from the listing (manual `/name` only).

3. **Eval-driven, contract-first.** No component is built before its contract and its
   eval set exist. Order is always: (a) contract (purpose, triggers, inputs/outputs),
   (b) `evals/evals.json` with numeric thresholds, (c) implementation, (d) pass the gate.
   Numeric thresholds are the definition of done.

4. **The eval pyramid.**
   - Tier 0 (static, always blocks): `skills-ref validate`, frontmatter lint, body
     <= 500 lines, references resolve, `pytest` green, `ruff` + `mypy` clean,
     script coverage >= 80%.
   - Tier 1 (trigger): should-trigger recall >= 0.9, should-not-trigger specificity >= 0.9.
   - Tier 2 (quality, LLM-judge, N >= 5 runs): (mean - sigma) pass-rate >= 0.8; token/time
     overhead within budget; A/B not worse than previous version.
   - Tier 3 (E2E): workflow scenarios pass with all checkpoints green.
   Thresholds are starting points; recalibrate per component and record the rationale.

5. **Python-only scripts, all tested.** No shell scripts. Skill-specific executables live
   in `skills/<name>/scripts/` (referenced via `${CLAUDE_SKILL_DIR}`); shared code lives in
   `plugin/lib/agentic_forge/` and is imported by scripts and hooks. Everything under
   `pytest`.

6. **Knowledge base.** The plugin deploys and maintains an Obsidian-format markdown vault
   in the target repo (`[[wikilinks]]` + maps-of-content), and reads it to enrich context.

## Layers

- L0 Meta-core: `skill-factory` + eval-harness + `lib/` + Tier-0 validator. Builds everything else.
- L1 Engine: subagent roles + native patterns (router, fan-out/fan-in, review loop, Ralph, worktree).
- L2 Workflow skills: a phase-workflow per SDLC phase (fan out → synthesize a handoff artifact), depth via references.
- L3 Knowledge base: Obsidian vault, recall skill, session-start injection.
- L4 Guardrails & observability: hooks (security, test-gate, logging, budgets).

## Repository layout

```
plugin/
  .claude-plugin/plugin.json
  skills/<name>/{SKILL.md, references/, assets/, scripts/, evals/evals.json}
  agents/<name>.md          # + agents/evals/<name>.evals.json (agent contracts)
  patterns/                 # engine pattern references (handoff, review loop, worktree)
  hooks/{hooks.json, scripts/*.py}        # L4 (planned)
  lib/agentic_forge/        # shared, importable, tested
  eval/{README.md, fixtures/}             # harness docs + agent eval fixtures
  schemas/                  # JSON Schema for evals.json + contract
tests/                      # pytest for lib + hooks + harness
dev/{validate.py, run_agent_evals.py}   # Tier-0 gate + agent Tier-2 runner (CLI)
docs/                       # product vision, architecture, ADRs, roadmap
CHANGELOG.md                # what changed, by milestone
```

## Documentation discipline

Document as you build, not after. Any change that adds, changes, or removes functionality
MUST, in the same unit of work:

1. Add a `CHANGELOG.md` entry (Added / Changed / Fixed / Removed).
2. Update the affected docs under `docs/` (vision, architecture, meta-core, roadmap).
3. Record any significant decision as an ADR in `docs/architecture/decisions/`.
4. Explain how the functionality works — not just that it exists.

Docs live in `docs/` and are the source of truth for intent and design; `CLAUDE.md` is the
rulebook. Plan and design a stage in `docs/` (goal, analysis, alternatives, exit criteria)
before implementing it.

## Editing rules

- All persisted content (skills, code, comments, docs) in English.
- `SKILL.md` body <= 500 lines; move detail to `references/` (one level deep).
- Use relative runtime paths and `${CLAUDE_SKILL_DIR}` / `${CLAUDE_PLUGIN_ROOT}`; never absolute user paths.
- Every model-invocable skill MUST ship `evals/evals.json` with thresholds, or Tier 0 fails.
- Run `python dev/validate.py` and `pytest` before every commit.
