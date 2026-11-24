---
type: release
feature: agentic-forge-2026.11.14
status: final
version: 2026.11.14
date: 2026-11-24
changelog:
  - "New pattern patterns/cheap-delegation.md: when a session hands bulk reading or mechanical multi-file edits to a fresh, cheaper, low-effort subagent, what never to delegate, the capped brief, the clerk's worktree pinned to the caller's commit, and the caller's check (ADR 0113)."
  - "The grader role sets omitClaudeMd: true, so a live delegation to it starts without CLAUDE.md; the eval harness is unaffected (ADR 0113)."
breaking: []
---
# Release 2026.11.14

The first two steps of open item 6 on board `known-issues` (subagent cost), with the proposal from thread 3c001b52
folded in. The owner chose to take item 6 in steps; ADR 0113 records the decision.

## What changed

- **`plugin/patterns/cheap-delegation.md`.** Field numbers from a twelve-session fleet: cache reads and writes were
  about 70 % of the spend and subagents 5 to 12 %, so the saving is the text that never enters the main context; and a
  cheaper default subagent model alone never made a session delegate. The pattern says:
  - **When:** the caller does not need the text verbatim, and the work is about four tool calls or 20k tokens of input
    (a failing run's log, a long diff or review thread, a sweep, a long document read for a few facts), or mechanical
    edits across files the caller has not read.
  - **When not:** a one-call edit, authored text, a verdict, anything that sends, pushes, merges or touches a secret,
    anything the caller must read anyway.
  - **How:** a fresh subagent, never a fork; a cheaper model and low effort named in the call, not host-wide; a brief
    with the answer's form and a line cap; a clerk keeps everything not named, changes nothing where an anchor is not
    unique, and works in its own worktree pinned to the caller's commit (`git checkout --detach <commit>`, since
    Claude Code branches a subagent worktree from the default branch unless `worktree.baseRef` is `"head"`).
  - **The check:** the worktree's staged file list equals the brief's list, then one item at its source, then the
    change is applied with `git apply --index` and the worktree removed.
  - **What holds it, said plainly:** nothing per call narrows a built-in subagent's tools, and a worktree isolates
    edits but is not a security boundary; only the host's enforced permissions or a sandbox stop an outward action.
- **The `grader` role starts without CLAUDE.md** (`omitClaudeMd: true`, Claude Code 2.1.271 or later; older versions
  ignore it). Everything it judges comes in the prompt. The eval harness passes the role body as the system prompt
  and is unaffected. The review lenses keep CLAUDE.md until an A/B.

## How it was checked

- Four review rounds (reviewer and the external lens, codex); round 4 was a verification round the owner approved
  after round 3 escalated. Final: both approve. Details in `review-code-4.md`.
- The `omitClaudeMd`, `worktree.baseRef` and `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` facts were checked against the Claude
  Code docs (sub-agents, plugins components, worktrees, env vars).
- Tier-0: `dev/validate.py`, `ruff`, `mypy` (including `plugin/bin`), the full pytest suite with coverage. No hook
  code changed, so `dev/hook_smoke.py` was not re-run.

## Not validated

No skill description changed. One role definition changed (`grader`), by a field the eval harness does not read, so
Tier-2 could not measure it; per the eval policy this release ran Tier-0 and the direct tests only.

- Tier-1 (trigger), Tier-1b (activation): not run. The pattern is not in the routing note, so routing is unchanged.
- Tier-2 (quality): not run. Whether a live session follows the pattern is not measured.
- Tier-3 (E2E spine): not run.

## Still open (item 6, waiting for live eval runs the owner accepts by cost)

- Low-cost `reader` and `clerk` roles (contract and Tier-2 eval set first).
- One routing-note sentence naming the pattern (with a Tier-1b run).
- Sonnet tiers for the existing roles through `VALIDATED_TIERS`, an A/B of `omitClaudeMd` for the review lenses, fresh
  model ids.
