# 0002 — Conform to the agentskills.io standard

Status: Accepted

## Context

Skills are an open standard (agentskills.io), adopted across many agents. Claude Code
implements it and extends it with optional fields. We want power without lock-in at the
artifact level.

## Decision

Every skill must pass `skills-ref`-style validation and conform to the standard. Claude
Code-specific behavior is expressed only through documented optional frontmatter fields.
The Tier-0 validator encodes the standard's rules (name, description, structure).

## Alternatives considered

- **Ignore the standard, optimize purely for Claude Code.** Rejected: forfeits portability
  and the discipline the standard imposes for little gain.
- **Lowest-common-denominator (standard only, no CC extensions).** Rejected: gives up
  subagents, forking, hooks, and dynamic context that make the plugin valuable.

## Consequences

- A single `SKILL.md` is both standard-valid and Claude-Code-powerful.
- Validator must track both the standard fields and the documented CC extension set, and
  warn (not fail) on unknown fields to allow forward compatibility.
