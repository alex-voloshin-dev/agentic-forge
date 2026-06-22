# Meta-core (Layer 0) — how it works

Layer 0 is the foundation that builds and gates every other component. It is fully
implemented and green (Tier-0 validator, unit tests, lint, types). This document explains
each piece and how they fit together.

## Why it exists and the bootstrap order

`skill-factory` is meant to create every component "evals-first", but it cannot validate
itself before the validator and harness exist. To avoid the chicken-and-egg trap, the
meta-core is built bottom-up and deterministically:

1. **Skeleton + shared lib + Tier-0 validator** — hand-written, covered by `pytest`. No
   LLM involved, so it is testable by ordinary means.
2. **Eval-harness** — deterministic aggregation and gate logic; LLM judgment is external
   (skill-creator), so our logic is unit-tested with plain data.
3. **Contract schema** — `evals.json` superset; the readiness definition.
4. **`skill-factory`** — the only component whose evals are hand-written (the bootstrap
   exception). It is then dogfooded by using it to produce gate-passing components.

## Repository layout (built)

```
plugin/
  .claude-plugin/plugin.json          # plugin manifest
  skills/skill-factory/               # the meta-skill (L0 deliverable)
    SKILL.md  references/  assets/  evals/evals.json
  lib/agentic_forge/                  # shared, importable, tested
    naming.py frontmatter.py evals.py validation.py benchmark.py gate.py
    handoff.py agent_eval.py          # L1/eval-harness additions
    spine_e2e.py stacks.py            # L2 spine: Tier-3 E2E + by-stack detection
  schemas/evals.schema.json           # the component contract schema (superset)
  eval/{README.md, fixtures/}         # harness architecture + agent eval fixtures (L1)
dev/{validate.py, run_agent_evals.py, run_spine_e2e.py}  # Tier-0 gate + agent Tier-2 + spine Tier-3 (CLI)
tests/                                # pytest for lib + harness + plugin integrity
pyproject.toml                        # uv / pytest / ruff / mypy config
.github/workflows/{ci.yml,eval.yml}   # Tier-0 always; Tier-1/2 cost-gated
```

## The shared library (`plugin/lib/agentic_forge/`)

| Module | Responsibility |
| --- | --- |
| `naming.py` | Validate skill names against the standard (1–64 chars, `a-z0-9-`, no leading/trailing/doubled hyphen, matches directory). |
| `frontmatter.py` | Parse YAML frontmatter into `(mapping, body)`; raise on missing/malformed blocks. |
| `evals.py` | Load `evals.json` and validate it against `schemas/evals.schema.json` (Draft-07). |
| `validation.py` | Tier-0 checks for skills, agents, and the manifest; aggregate into a `Report`. |
| `benchmark.py` | Aggregate per-run `grading.json` pass rates into a `benchmark.json` shape (mean/stddev/n, delta). |
| `gate.py` | Apply thresholds: `trigger_metrics`, `tier1_trigger`, `tier2_quality`, `evaluate`. Pure functions. |
| `handoff.py` | Load + validate SDLC handoff artifacts (Markdown + frontmatter) against per-type header schemas (L1). |
| `agent_eval.py` | Tier-2 quality runner for subagent roles, over a pluggable model seam (eval-harness; see ADR 0011). |
| `spine_e2e.py` | Tier-3 end-to-end runner for the SDLC spine: carry a feature through all six phases on an isolated fixture copy, with per-phase checkpoints (L2). |
| `stacks.py` | Deterministic stack detection for target repos: `detect`/`primary` from hints/manifests plus the toolchain registry the spine's `develop`/`code-review` consume (by-stack; ADR 0015). |

Everything here is dependency-light (pyyaml, jsonschema) and unit-tested. Skill scripts and
hooks import from this package.

## Tier-0 validator (`dev/validate.py`)

A CLI that walks `plugin/skills/*` and `plugin/agents/*.md` and runs `validation.py`. For
each skill it checks: directory/name rules, required non-empty `description` (≤1024), body
≤500 lines, that local `references/`, `assets/`, `scripts/` links resolve, and that a valid
`evals/evals.json` (with `component.type: skill`) exists. Each agent is gated the same way:
a sibling contract at `plugin/agents/evals/<name>.evals.json` with `component.type: agent`
is required. Errors fail the gate (exit 1); warnings (e.g. unknown frontmatter field) never
fail. Standard fields and documented Claude Code extension fields are both recognized;
anything else warns as a possible typo.

Coverage and types are part of Tier 0 too, enforced in CI: `pytest --cov=agentic_forge
--cov-fail-under=80`, `ruff`, and `mypy` (see [ci.yml](../../.github/workflows/ci.yml)).

Run it:

```bash
python dev/validate.py            # validates ./plugin
python dev/validate.py <path>     # validates a specific plugin dir
```

## Eval harness (hybrid on skill-creator)

agentic-forge does not run or grade LLM evals itself — the official `skill-creator` loop
does that (isolated subagent runs, assertion grading to `grading.json`, timing capture).
The meta-core adds the **policy layer**:

- `benchmark.summarize(with_skill, without_skill, with_skill_timing=…, without_skill_timing=…)`
  turns `grading.json` (and optional `timing.json`) lists into the aggregate `benchmark.json`
  shape, including the with/without pass-rate delta and the token/time overhead delta.
- `gate.tier2_quality(benchmark, thresholds)` passes only when the pass-rate **lower
  bound** `mean − stddev` over the required number of runs meets `min_pass_rate`, and the
  token/time overhead delta (when timing is supplied) stays within budget. Gating on the
  lower bound absorbs LLM run-to-run noise.
- `gate.trigger_metrics(...)` + `gate.tier1_trigger(...)` score auto-loading: recall over
  should-trigger prompts, specificity over should-not-trigger prompts.

See [../../plugin/eval/README.md](../../plugin/eval/README.md) for the full division of
labour and flow.

## The contract: single-file `evals.json` superset

Each component ships exactly one `evals/evals.json`, a **superset** of the skill-creator
format (`schemas/evals.schema.json`):

- `skill_name`, `evals[]` (`id`, `prompt`, `expected_output`, `files`, `assertions[]` as
  strings) — read by skill-creator.
- `component` (`id`, `type`, `purpose`), `thresholds` (tier1/tier2/tier3), `triggers`
  (should/should-not) — read by agentic-forge; ignored by skill-creator.

One file, two consumers. The schema requires the superset keys and rejects malformed
contracts, so Tier-0 enforces "evals exist and are well-formed" before any body is judged.

## `skill-factory` (the meta-skill)

A router-pattern skill: a lean `SKILL.md` (well under the 500-line cap) plus references per component type
(`skill.md`, `agent.md`, `script.md`) and the `eval-loop.md` guide, with templates in
`assets/`. It encodes the standing process — **contract → evals → implementation → gate** —
and refuses to write a component body before its `evals/evals.json` exists. v1 builds
skills, subagents, and Python scripts.

Its own `evals/evals.json` is hand-written (the bootstrap exception — every other component
gets its evals via `skill-factory`). It declares the standard Tier-1/Tier-2 thresholds and
is gated like any skill once the skill-creator loop is run against it; today it is enforced
at Tier 0, and the plugin-integrity test dogfoods that the whole plugin passes its own
Tier-0 gate.

## CI

- `ci.yml` runs the Tier-0 gate on every push/PR: `validate`, `pytest`, `ruff`, `mypy`.
- `eval.yml` runs Tier-1/2 on demand or when a PR is labelled `eval`. The agent Tier-2 runs
  on a Claude **subscription** token (`CLAUDE_CODE_OAUTH_TOKEN`) via the `claude` CLI and
  deliberately leaves `ANTHROPIC_API_KEY` unset (it would override the subscription); the
  skill path uses skill-creator, and the optional `--runner api` path uses
  `ANTHROPIC_API_KEY`. This keeps expensive LLM evals off the always-on path.

## How to extend

Use `skill-factory`: load the plugin in a Claude Code session (`claude --plugin-dir
plugin`), then describe the component — `skill-factory` auto-loads and writes the contract
and evals first, before you implement and run the gate (see
[handoff-to-cli.md](../handoff-to-cli.md) §4). The plugin-integrity test guarantees nothing
merges that breaks Tier-0.
