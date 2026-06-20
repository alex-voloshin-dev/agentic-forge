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
  - [Engine (Layer 1) design](architecture/engine.md) — Stage 1 worked design: roles,
    handoff artifacts, review loop, agent eval (pre-implementation).
  - [Decision records](architecture/decisions/README.md) — the ADRs behind every major
    choice.
- **Plan**
  - [Roadmap](roadmap.md) — staged work plan; each stage analyzed before implementation.
  - [Handoff to CLI](handoff-to-cli.md) — how to continue implementation in Claude Code CLI.
- **Change history**
  - [CHANGELOG](../CHANGELOG.md) — what was added/changed/fixed, by milestone.

## Reading order for a newcomer

1. Vision → 2. Architecture overview → 3. Roadmap → 4. Meta-core → 5. ADRs as needed.
