# agentic-forge documentation

Start here. Documentation is written alongside the work, not after it (see the
documentation discipline in the root `CLAUDE.md`).

## Map

- **Product**
  - [Vision & design](product/vision.md) — goal, problem, users, scope, success metrics.
- **Architecture**
  - [Overview](architecture/overview.md) — the five layers, component taxonomy, patterns,
    the eval pyramid, constraints.
  - [Meta-core (Layer 0)](architecture/meta-core.md) — how the built foundation works:
    validator, library, harness, gate, `skill-factory`, CI.
  - [Engine (Layer 1)](architecture/engine.md) — Stage 1 (implemented): roles,
    handoff artifacts, review loop, agent eval.
  - [Decision records](architecture/decisions/README.md) — the ADRs behind every major
    choice.
- **Plan**
  - [Roadmap](roadmap.md) — staged work plan; each stage analyzed before implementation.
  - [Handoff to CLI](handoff-to-cli.md) — how to continue implementation in Claude Code CLI.
- **Change history**
  - [CHANGELOG](../CHANGELOG.md) — what was added/changed/fixed, by milestone.

## Reading order for a newcomer

1. Vision → 2. Architecture overview → 3. Roadmap → 4. Meta-core → 5. Engine (Layer 1) →
6. ADRs as needed.

When building a component or running evals: use `skill-factory` (load the plugin in a Claude
Code session, then describe the component — [handoff-to-cli.md](handoff-to-cli.md) §4), and
see the [eval runbook](eval-runbook.md) and the [eval harness](../plugin/eval/README.md).

## Glossary

- **Layer / Stage** — they map 1:1 (Stage N builds Layer N): L0/Stage 0 meta-core, L1/Stage 1
  engine, L2/Stage 2 workflow skills, and so on.
- **Router discipline** — keeping the always-on, model-invocable skill set small with sharp
  descriptions so the skill listing stays within its context budget.
- **Listing budget** — the ~1% of the model's context window the always-on skill
  name+description listing may occupy; overflow drops descriptions and degrades auto-loading.
- **Progressive disclosure** — depth lives in `references/` loaded on demand, not in the
  always-on listing.
- **Ralph loop** *(deferred)* — a bounded, self-restarting agent loop for long autonomous tasks.
- **MOC (map-of-content)** — an index note linking related knowledge-base notes, used for
  navigation instead of folders (knowledge base, Stage 3).
- **Fidelity level (agent evals)** — level-1 judges a role's text output (no tools); level-2
  runs the role with real tools in a workdir. See the [eval runbook](eval-runbook.md).
- **The seam** — the pluggable model/agent-invocation function in the eval runner, so the
  orchestration is unit-testable with stubs.
- **Policy layer** — agentic-forge's deterministic `benchmark` + `gate` on top of the
  skill-creator / agent-runner engines.
- **Superset (`evals.json`)** — one file read by both skill-creator (`skill_name`, `evals`)
  and agentic-forge (`component`, `thresholds`, `triggers`).
