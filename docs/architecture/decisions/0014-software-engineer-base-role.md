# 0014 — One software-engineer base role + stack skills, not per-stack agents

Status: Accepted

## Context

ADR 0009 created a generic `implementer` role; ADR 0013 sketched the Stage 2 roster as
"stack engineers (`software-engineer` + `python-engineer`, later `frontend-/db-/...`)". As we
started Stage 2 we refined the model: rather than one agent per language/framework (the
ancestor `ai-skills` approach, which spawns a `python-engineer`, `frontend-engineer`, …), use
**one base engineering agent** that adapts to the project's stack by **loading
stack-specific skills** chosen from context (CLAUDE.md / AGENTS.md / repo detection). The
ancestor itself models this as a "base role (Layer 1) + stack specializations (Layer 2)"; we
keep the base role and move the specialization into skills, so we don't multiply near-identical
agents. We also keep both the agent and the skills **lean** — Claude already knows general
engineering concepts; we encode only what is project- or stack-specific.

## Decision

- **Rename `implementer` → `software-engineer`**: the base engineering role, language- and
  framework-agnostic, used as the implementation target in `develop`. (Supersedes the
  `implementer` naming in ADR 0009 and the per-stack-engineer roster note in ADR 0013.)
- **Stack specialization lives in skills, not agents.** `software-engineer` loads, by context,
  a lean **`engineering-standards`** skill (the principles we always apply) plus the relevant
  **stack skill** (e.g. a `*-patterns` skill) for the detected language/framework. No
  per-stack agents.
- **Stack skills are off-listing knowledge** (`disable-model-invocation: true`), loaded on
  demand — consistent with the corrected router discipline (ADR 0004). They arrive in the
  **by-stack step** (after the thin slice); Python is the first stack.
- **Lean by default.** Neither the agent body nor the skills restate concepts the model
  already knows; they carry only project/stack-specific standards and conventions. (We
  explicitly do **not** copy the ancestor's runtime-protocol bloat.)
- **New quality specialists are real agents** (not stack variants): `security-engineer` and
  `qa-engineer` are added because they are distinct capabilities, each gated at Tier-2.

## Alternatives considered

- **One agent per stack** (ai-skills' `python-engineer`, `frontend-engineer`, …): rejected —
  multiplies near-duplicate agents; stack idioms are data (skills), not separate executors.
- **Keep the name `implementer`**: rejected — `software-engineer` is the base-role name in the
  domain and in the ancestor; the rename removes ambiguity (chosen over minimal-churn).
- **Fold the principles into the agent body**: rejected — a separate `engineering-standards`
  skill is reusable by reviewers/QA and keeps the agent lean.

## Consequences

- The role set is now: base `software-engineer`; design `architect`; quality `reviewer`,
  `grader`, `security-engineer`, `qa-engineer`. Stack coverage scales via skills, not agents.
- The `develop` impl fan-out targets `software-engineer` (which loads the stack skill); the
  by-stack step adds stack skills + a detection helper.
- `implementer` references across the living docs/code were renamed to `software-engineer`;
  ADRs 0009/0011 and historical CHANGELOG entries keep the old name as record.
- `engineering-standards` is a lean, off-listing knowledge skill, exercised through
  `software-engineer`'s Tier-2 rather than independently triggered.
