# 0004 — Skill-centric with router discipline

Status: Accepted

## Context

The product bet is that users describe tasks and the right workflow loads itself, rather
than invoking agents/commands by hand. But Claude Code's skill listing has a context budget
(~1% of the model window); with many skills, descriptions of rarely used ones are dropped,
degrading auto-loading.

## Decision

Make skills the primary unit and keep a **small** set of always-on, model-invocable entry
(router) skills with sharp descriptions. Push depth into `references/` and
`user-invocable: false` sub-skills (progressive disclosure). Agents are executors skills
delegate to; hooks are guardrails. Users do not call agents directly.

## Alternatives considered

- **Flat catalog of many auto-loaded skills.** Rejected: overflows the listing budget and
  silently breaks routing as the catalog grows.
- **Command/agent-centric (explicit invocation).** Rejected: contradicts the product bet of
  meeting the user at their request.

## Consequences

- One router skill per domain; sub-skills and references carry detail.
- Routing quality is itself an eval target (Tier 1), and listing-budget headroom is a
  tracked health metric.
