# 0077 — Eval runs load project settings only, never the operator's

**Status:** Accepted (implemented)
**Date:** 2026-07-26
**Refines:** 0064 (which system-prompt flag carries the component body).

## Context

Running two Tier-2 suites that had never been executed (ADR 0073's new cases) produced graded
artifacts written **in Russian**. Nothing in the plugin, the skill body, the case prompt, or the
grader asks for Russian. The source was the maintainer's own `~/.claude/CLAUDE.md`, which carries a
personal *"always answer in Russian"* rule.

The mechanism: ADR 0064 established that a skill body is delivered with `--append-system-prompt`,
so the skill runs **on top of** Claude Code's real system prompt — deliberately, because that is how
a user experiences it. But "Claude Code's real system prompt" also includes the operator's
user-level settings and `CLAUDE.md`. The eval therefore measured *the skill plus whoever ran it*.

Verified directly:

```
$ echo "Say hello in one short sentence." | claude -p --model claude-opus-4-8
Привет! Рад помочь вам с задачами по разработке.
$ echo "…" | claude -p --model claude-opus-4-8 --setting-sources project
Hello! How can I help you today?
```

Consequences, in order of severity:

1. **Tier-2 numbers were not comparable across machines.** A pass rate recorded here and one
   recorded by another maintainer measured different systems. The whole point of a numeric
   threshold is that it means the same thing twice.
2. **A personal rule can move a gate.** Not hypothetically — a language rule changed the artifacts
   the grader read. A stricter personal directive ("never write tests", a house review style)
   could plausibly push a borderline case across a threshold in either direction.
3. **The version-over-version benchmark history (ADR 0047) inherits the flaw**, since a stored
   number and a later comparison may come from different environments.

## Decision

`agent_eval.claude_cli_runner` passes **`--setting-sources project`** on every eval invocation.
Project settings — the repository under test — still load; the operator's `user` and `local`
sources do not.

This is deliberately *not* a switch to `--system-prompt` (`replace_system`). Replacing the system
prompt would also discard Claude Code's own scaffolding, so the run would no longer resemble what a
user gets. The defect was never that the component runs on top of Claude Code; it was that it ran
on top of **one particular person's** Claude Code. ADR 0064's choice stands; only the environment is
isolated.

Subscription auth is unaffected — credentials are not a settings source, and the isolated
invocation above authenticated normally.

## Consequences

- **Tier-2 and Tier-1 numbers become machine-independent**, which is what makes a recorded
  benchmark meaningful at all.
- **Previously recorded numbers were taken under the old regime** and are not strictly comparable
  with numbers taken after this change. They are not invalidated — nothing suggests the language
  drift changed a verdict — but a cross-version comparison spanning this commit should be read with
  that in mind.
- **A project-level `.claude/` in a repo under test still participates.** That is intended: it is
  part of the artifact being evaluated, and it is committed, so it is the same for everyone.
- **The gap existed for every eval this project has ever run.** It was found only by running a
  suite and *reading the artifacts* rather than the pass rate — the same "inspect content, not
  counts" rule ADR 0073 imported from the field report, applied to our own harness.
