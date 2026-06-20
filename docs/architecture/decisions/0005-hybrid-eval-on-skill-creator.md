# 0005 — Build the eval engine on skill-creator

Status: Accepted

## Context

Anthropic's official `skill-creator` already runs the eval loop: isolated subagent runs
with/without the skill, assertion grading to `grading.json`, timing capture, benchmark
aggregation, blind A/B, and description tuning. We need Tier-1/2 mechanics.

## Decision

Use `skill-creator` as the eval engine for skills. agentic-forge adds a thin **policy
layer**: deterministic benchmark aggregation (`benchmark.py`) and a threshold gate
(`gate.py`), plus `pytest` for scripts/hooks and a thin task-success harness for agents.

## Alternatives considered

- **Build a full custom harness.** Rejected: large, duplicative, and risks drifting from
  the upstream format.
- **Defer the decision.** Rejected: the contract format depends on it.

## Consequences

- Less code to own; we inherit upstream improvements.
- We depend on skill-creator's format and behavior; mitigated by the single-file superset
  (ADR 0006) and by owning only the deterministic gate math.
- Agents/scripts are not covered by skill-creator; we add small harnesses for those.
