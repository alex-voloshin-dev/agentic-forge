# ADR 0113 — Cheap delegation, first steps: the pattern, and the grader without CLAUDE.md

Status: Accepted (implemented)
Date: 2026-11-24

Builds on [0043](0043-multi-model-tiers.md) and [0046](0046-runtime-model-routing.md) (a role runs on a cheaper
tier only after it passes its gate there) and [0073](0073-subagent-dispatch-containment.md) (a fresh
subagent, never a fork, for work that must not act).

## Context

Open item 6 on the field board: every role is `model: inherit`, so each subagent runs on the session's model. Thread
1212fbfd asked for cheaper roles; thread 3c001b52, from the manager session of a twelve-session fleet, added field
numbers and a proposal:

- **Cache reads and writes were about 70 % of the fleet's spend; subagents were 5 to 12 %** (two days, API-equivalent
  cost read from the transcripts). The lever is the length of the main context, not the subagent's price.
- A low-effort Sonnet "reader" kept about 25k characters out of a 270k-token main context for one task; a "clerk" made
  four listed edits in three files in two tool calls. A one-call edit cost more delegated than done.
- With a cheaper default subagent model set host-wide, no session started delegating in two weeks: nothing said when.

It proposed (1) a pattern saying when to delegate, (2) low-cost `reader` and `clerk` roles with their model and
effort in their frontmatter, and (3) one sentence in the routing note naming the pattern. Item 6's own plan adds
Tier-2 at Sonnet to promote roles through `VALIDATED_TIERS`, `omitClaudeMd` on the grader, an A/B of `omitClaudeMd`
for the review lenses, and fresh model ids.

The owner chose to take it in steps (2026-11-24): first what needs no model-backed eval run, then the rest with its
runs.

## Decision

**Step 1: `plugin/patterns/cheap-delegation.md`.** When to delegate (the caller does not need the text verbatim, and
the work is about four tool calls or 20k tokens of input), when not to (a one-call edit, authored text, a verdict,
anything that sends, pushes, merges or touches a secret, anything the caller must read anyway), the brief (the
answer's form and a line cap; a clerk keeps everything not named and changes nothing where an anchor is not found
exactly once), the subagent (fresh, never a fork; a cheaper model and low effort named in the call, not host-wide, so
the roles that review and decide keep theirs; a clerk always in its own worktree, pinned to the caller's commit by its
first step, because a Claude Code subagent worktree branches from the default branch unless `worktree.baseRef` is
`"head"`; the caller commits its own work first when the edits belong on top of it), and the caller's one check at the
source, starting with the worktree's staged file list against the brief's. The pattern says plainly what holds it:
nothing per call narrows a built-in subagent's tools (only its agent type, the user's permission rules and the brief),
and the worktree isolates edits but is not a security boundary, so only the host's enforced permissions or a sandbox
stop an outward action. `fan-out-fan-in.md` links it as its one-unit case.

**Step 2: the grader starts without CLAUDE.md.** `plugin/agents/grader.md` sets `omitClaudeMd: true` (Claude Code
2.1.271 or later; plugin agents support the field). Everything the grader judges comes in the delegation prompt: the
output and the assertions. The project's rules are not its input, and a rule in them ("always answer in <language>")
could only bend a grading. Managed policy files still load. Only the grader: the review lenses read CLAUDE.md as the
project's rules on purpose, so dropping it from them waits for an A/B.

*Note 2026-11-27: the `reader` role now omits CLAUDE.md too, for the same reason ([ADR 0116](0116-the-reader-role-the-clerk-deferred.md)); the lenses still read it.*

## Not done here, and why

- **`reader` and `clerk` roles.** A new role is a component: contract and Tier-2 eval set first (ADR 0008), then live
  runs at its tier. They come with the Tier-2 run below.

  *Note 2026-11-27: [ADR 0116](0116-the-reader-role-the-clerk-deferred.md) ships the `reader` with its contract and Tier-2 set (not yet run) and defers the clerk until
  the `role_scope` hook can hold it.*
- **The routing-note sentence.** The routing note shapes how every session sizes its process; the last change to it
  measured 0.863 pooled on Tier-1b against a 0.940 baseline. A sentence goes in with its own Tier-1b run.
- **Sonnet tiers for the existing roles, the lens A/B, fresh model ids.** These need live Tier-2 runs, which the owner
  accepts by cost before they start.

## Consequences

- The pattern is reachable from `fan-out-fan-in.md` and the engine docs, not from the routing note, so a session meets
  it when it reads about delegation; whether sessions then delegate is measured only after the routing-note sentence
  (see "Not done here").
- The grader's field has no effect on the eval harness: `run_agent_evals` and `run_skill_evals` pass the role body as
  the system prompt and never read this field. It acts only when a session delegates to `grader` live. On a Claude
  Code older than 2.1.271 the field is ignored and the grader loads CLAUDE.md as before.
- Tier-0 pins both: the pattern's load-bearing wording and its index entries, and that `grader` is the only role that
  omits CLAUDE.md.

  *Note 2026-11-27: since [ADR 0116](0116-the-reader-role-the-clerk-deferred.md) the pin is that `grader` and `reader` are the only roles that omit it.*

## Amendment 2026-11-27: the routing-note sentence

The step held back under "Not done here" is taken. After the two routing sentences, the SessionStart note now says:

> For large bulk reading (a log, diff or document read only for a few facts) or a mechanical multi-file edit, delegate
> to a low-cost subagent with a short brief and keep the judgement yourself; when and how:
> `<plugin>/patterns/cheap-delegation.md`.

- **Where the path comes from.** `session_start.routing_note()` fills in the pattern's absolute path in this install,
  so the session can `Read` it as given. The configuration doc quotes the sentence with a `<plugin>` placeholder, and a
  test checks that the doc quotes it verbatim.
- **Cost and switch.** About 240 characters at every session start and after every compaction. The same switch
  (`routing_note.enabled`, `AGENTIC_FORGE_ROUTING_NOTE=0`) turns it off with the rest of the note.
- **Tier-1b, before and after.** Both runs used Opus 5.5 (`claude-opus-5-5`), the default fixture repo per prompt and
  measure only, with the same 80 prompts over 16 shipped skills:
  - before (master 798ba5c, v2026.11.18): 0.975 pooled (78/80);
  - after (this change): 0.975 pooled (78/80).

  The per-skill rates are identical: ux-design 3/4, marketing 8/9, every other skill 100 %. So the sentence does not
  cost activation.
- **What this does not measure.** Whether sessions now delegate bulk reading. No harness counts delegations. The field
  fleet that reported "no session started delegating until a pattern said when" is the instrument; the thread is
  asked to report back.
