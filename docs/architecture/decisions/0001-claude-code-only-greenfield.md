# 0001 — Claude Code only, greenfield repo

Status: Accepted

## Context

A prior repo (`ai-skills`) shipped the same assets across Claude Code, Codex, and Windsurf,
carrying multi-vendor parity overhead and project-specific (friendly4AI) content. The new
effort targets Claude Code exclusively and wants to use its native primitives fully.

## Decision

Build a new, greenfield plugin (`agentic-forge`) for Claude Code only. Reuse the old repo
as a content source, not as a base. No multi-vendor packaging.

## Alternatives considered

- **Evolve `ai-skills` in place.** Rejected: drags multi-vendor structure and legacy
  assumptions; harder to enforce strict new rules.
- **New `plugin/` inside the old repo.** Rejected: keeps legacy alongside and muddies the
  constitution.

## Consequences

- Free to use Claude-Code-only features (subagents, forked skills, hooks, plan mode) without
  a portability tax.
- Lose cross-runtime reach; acceptable given the explicit single-vendor goal.
- Standard compliance (ADR 0002) preserves skill-level portability regardless.
