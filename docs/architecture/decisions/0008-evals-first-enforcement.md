# 0008 — Enforce evals-first via instructions + Tier-0

Status: Accepted

## Context

The process rule is "contract → evals → implementation → gate". We need it enforced without
making authoring painful.

## Decision

Enforce evals-first through `skill-factory`'s standing instructions plus the Tier-0 gate,
which fails any skill lacking a valid `evals/evals.json`. No blocking hook in v1.

## Alternatives considered

- **PreToolUse hook** that blocks writing `SKILL.md` before `evals.json` exists. Rejected
  for v1: more machinery and friction for marginal gain, since Tier-0 already blocks merge.
- **Both hook and instructions.** Rejected for v1: extra code and potential noise.

## Consequences

- Lower friction; the gate is the backstop. A component without evals cannot pass CI.
- If discipline slips in practice, revisit the hook option (cheap to add later).
