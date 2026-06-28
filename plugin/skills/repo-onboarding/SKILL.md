---
name: repo-onboarding
description: Onboard to an unfamiliar or new CODEBASE / REPO — analyze its whole structure (components, entry points, conventions, risks) and seed the project knowledge vault from it, producing an onboarding map. Use to onboard to / get oriented in / understand a new or unfamiliar codebase or repo, or to analyze a repo and seed the knowledge base from it. Seeding the vault from a whole codebase is part of THIS skill; capturing or recalling a single decision or note is knowledge. Not feature/options research (research) or reviewing a change (code-review).
allowed-tools: Read, Grep, Glob, Bash, Task, Write, Edit
---

# Repo onboarding (phase workflow)

Get oriented in an unfamiliar codebase and leave behind a durable map: analyze the structure and
**seed the Stage-3 knowledge vault** with grounded notes, plus an `onboarding` summary. It reads
the code (forking `Explore`) and writes notes via the installed `agentic_forge.vault` module —
everything grounded in the actual code, nothing invented. (Design:
[ADR 0023](../../../docs/architecture/decisions/0023-stage6-design-onboarding.md),
[design-onboarding.md](../../../docs/architecture/design-onboarding.md).)

## When to use

When the task is to understand / get oriented in an unfamiliar or new codebase, or seed the KB from
a repo. **Not** feature/options research (`research`), reviewing a change (`code-review`), or
capturing one decision (`knowledge`).

## Process

The vault helpers are an **installed module** — call them with Python, never look for a file:

```
python -c "from agentic_forge import vault; print(vault.validate_vault('.'))"
```

1. **Analyze the code.** Fork `Explore` (via `Task`) to map the repo: the components/modules, the
   entry points (how it runs), the conventions (error handling, structure, testing), and the
   notable risks/gotchas. Detect the stack (`stacks.primary`) for context. Stay grounded — every
   claim must point at real code; do not invent modules or features.
2. **Seed the vault.** For each durable finding, write an atomic note with
   `vault.add_note(repo, name, title, body, tags=..., moc=...)` — an architecture map, key
   components, conventions, risks — linked from a themed MOC. Then `vault.validate_vault(repo)` and
   fix any broken link or orphan.
3. **Write the `onboarding` map** (`handoff` type `onboarding`: `type`, `feature`, `status`, `components`, `entry_points`,
   `conventions`, `risks`) — the quick-start summary that points into the seeded vault.

## Output

A seeded knowledge vault (atomic notes, linked, validating clean) plus an `onboarding` handoff
mapping components, entry points, conventions, and risks — all grounded in the real code.

## Definition of done

- Components, entry points, conventions, and risks are identified **from the actual code** (nothing
  fabricated).
- The vault is seeded with linked notes and `validate_vault` is clean (no broken links/orphans).
- A valid `onboarding` artifact is produced.
