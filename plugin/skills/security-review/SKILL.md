---
name: security-review
description: Run a dedicated deep security review of a component, design, or change — threat surface, authz, secrets, dependencies, input handling — by delegating to the security-engineer role, and record a review handoff with a security lens. Use to security-review, security-audit, threat-model, or check whether code is secure / find vulnerabilities. Not the per-diff security aspect of a general code review (code-review), implementing fixes (develop), or cutting a release (release).
allowed-tools: Read, Grep, Glob, Bash, Task, Write, Edit
---

# Security review (phase workflow)

A dedicated, deeper security pass over a whole target — a component, a design, or a change —
distinct from the per-diff security aspect inside `code-review`. It delegates the security
judgement to the [`security-engineer`](../../agents/security-engineer.md) role and records a
`review` handoff (security lens): findings with severity, location, and fix, aggregated into one
verdict. (Design: [quality-ops.md](../../../docs/architecture/quality-ops.md).)

## When to use

When the task is a deep, whole-target security audit or threat model — "is this secure?", "audit
this for vulnerabilities", "threat-model X". **Not** the inline security aspect of a routine
change review (`code-review` already runs `security-engineer` per diff), implementing fixes
(`develop`), or releasing (`release`).

## Process

1. **Scope the target.** Identify what is under review (component / design / change) and gather it
   — source, dependency manifest, the relevant config — plus the trust boundaries and entry points.
2. **Delegate the review.** Fork the `security-engineer` role (via `Task`) with the target and the
   threat surface to examine: input validation, authz/authn, injection, secrets handling,
   dependency risk, unsafe deserialization. The role brings the security expertise.
3. **Aggregate into a verdict.** Collect findings into a `review` handoff (`handoff` type `review`:
   `target`, `iteration`, `verdict`, `findings` with `severity`/`location`/`suggestion`). Any
   `blocker`/`major` finding makes the verdict `changes`; otherwise `approve`.
4. **Report, don't fix.** Surface findings with concrete locations and remediations; do not modify
   code. Do not invent vulnerabilities on safe code — an approve with at most nits is a valid result.

## Output

A `review` handoff (security lens): the verdict plus severity-tagged findings with locations and
fixes. Hand off to `develop` to remediate. No files are modified.

## Definition of done

- Real vulnerabilities are flagged with a location, a severity, and a concrete fix.
- The verdict reflects the findings (`changes` if any blocker/major; else `approve`).
- A valid `review` artifact is produced; no code is modified; nothing is invented on safe code.
