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

## Amendment 2026-11-27: the agent-eval harness applies `omitClaudeMd`

**The gap.** The consequence above, "the grader's field has no effect on the eval harness", made the planned A/B
for the review lenses impossible: the harness never read the field, so a run with it and a run without it were
the same run. It also meant the field barely acted at all, since the harness is the grader's main caller. And
nothing in an isolated eval workspace was a project CLAUDE.md for a lens to lose.

**Decision.** `run_agent_evals` (the `claude` runner) honours `omitClaudeMd` for the role under test and for the
judge. Each session gets `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` when its role omits CLAUDE.md, `=0` when it does not.

- **Why this variable.** The CLI offers no flag for it. `--bare` skips CLAUDE.md but forces API-key auth, which
  would break the subscription path the runbook recommends. `--safe-mode` also turns off skills, plugins and
  hooks, so it would change more than the one thing measured. Checked on Claude Code 2.1.331 with no model call:
  the API was a local capture server, and only the variable changed between two sessions in the same workspace.
  Unset or `0`, the memory loader walks every ancestor of the working directory for `CLAUDE.md`,
  `.claude/CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md` and `.claude/AGENTS.md`. With `1`, the debug log says
  `project memory is off`. The binary's loaders return early on the variable. A second probe confirmed the load
  itself. Its workspace was a `mktemp -d` under `/tmp`, outside any session scratchpad, with the fixture as
  `CLAUDE.md`. At `0`, the request the session would have sent carried the fixture's heading and its index rule, and
  was 8,792 bytes longer. At `1`, it carried neither. One difference from the field: managed policy files go too,
  which matters only on a machine that has one. `run_skill_evals` pins `0`, its old behaviour, so a `1` exported in a
  shell cannot strip CLAUDE.md there either. The field must be the literal `true`/`false` (Tier-0); PyYAML would
  also read `yes`/`on` as true, and Claude Code need not.
- **The A/B override.** `--omit-claude-md {role,on,off}` (default `role`, which follows the frontmatter) forces it
  for the role under test. The judge always follows `grader.md`, so both arms are graded alike.
- **A project CLAUDE.md to lose.** `--claude-md <path>` copies the file into each case's fresh workspace, with
  isolation forced. Both arms get the same file and differ only in the variable. The fixture is
  `plugin/eval/fixtures/claude-md/typical-project.md`, a plausible project's rules. Two of its rules match
  assertions the lenses already carry: the index check that covers negative wrap (reviewer case 1) and no secret in
  a log line (security-engineer case 2). Losing the file could show there.
- **A loading trap.** Claude Code 2.1.331 does not load a CLAUDE.md under a session scratchpad or `.artifact-work`
  (its debug log: "not loading ... is in a session's scratchpad"). `--claude-md` therefore refuses to start when
  the temp directory is such a path.
- **The record.** The benchmark stores `omit_claude_md`, `omit_claude_md_mode`, `grader_omit_claude_md`, `claude_md`
  (the file name and a 12-hex SHA-256), `runner` and `claude_version`. In `run_agent_evals`, the version check
  compares a run only with records of the same setup: the CLAUDE.md fields and the runner. An older record counts as
  `off` for both role and judge, with no file and no runner, which is what those runs had. Because the judge now
  omits CLAUDE.md, the first recorded run of every role after this change starts a fresh baseline. That is the ADR
  0114 rule: a changed instrument is another instrument. `claude_version` is not compared there, since every CLI
  update would reset the baselines; it is compared between A/B arms. `run_skill_evals` records none of these fields.
- **The manipulation check is a probe.** If the CLI ignored the switch, or the workspace sat where it loads nothing,
  the two arms would be the same run, and an identical pair would read as "no loss". A token total cannot catch
  that: a role session sums up to 40 turns that each re-read the whole cached context, so turn count alone moves it
  by more than a CLAUDE.md, and two identical arms passed a token floor about half the time (round-2 review). So
  every `--claude-md` run also runs one probe session per role.
  - **Built like the role's.** Same component environment (switch and pinned variables), same model, same system
    prompt, a workspace made as a case's is (`mkdtemp` plus the file), one turn, no tools.
  - **Asked one question.** "Quote the first Markdown heading of the project CLAUDE.md you were given, or reply
    NONE. Reply with the heading text only." The answer is kept whole, up to 4,000 characters, so a heading after a
    preamble is found. `--claude-md` refuses a file whose first heading is generic: under 12 characters or one word,
    or part of the question or of `none`.
  - **Judged per arm.** The off arm must quote the file's first heading and the on arm must not. An arm whose probe
    is not as expected, or whose probe session failed, is INVALID on its own and the run exits 1. An INVALID arm is
    never recorded as a benchmark baseline, even with `--record` (round-4 review).
  - **Recorded.** Each arm goes to `claude-md-ab.json` beside the history, healthy or not, because the arm that lost
    quality is the one that matters. The record holds the probe's answer, prompt tokens and verdict, an input
    `fingerprint`, the git commit, a dirty flag and a timestamp. The fingerprint is a SHA-256 over the role,
    `grader.md`, the role's contract, its case fixtures and the file.
  - **Written safely.** The file is written atomically. A malformed file is refused, not overwritten.
  - **Paired.** A pair is the other arm with the same role, model, judge, file, runner, `claude --version` and
    fingerprint. It is VALID only if both probes were as expected, and the run prints the paired arm's commit and
    time. It warns when the arms ran at different commits or a different number of runs. An arm whose
    `claude --version` is unknown is never paired.
  - **Information only.** The probe's token difference and the arms' `prompt_tokens/run` and `cost/run` are the
    measured saving, not the test. Those figures count every answered role session per run, graded or not.
- **The on arm still has the file.** It is not loaded, but a lens can `Glob` or `Read` it as a plain file, as it can
  in a real repository. The runbook tells the operator to check the on arm's transcripts for a read before
  concluding.
- **Token accounting.** The CLI envelope's `usage` adds up over the session's turns, and its `input_tokens` leaves
  out the cached prompt, where a CLAUDE.md sits. The runner now keeps `cache_read_input_tokens` and
  `cache_creation_input_tokens`, their sum with `input_tokens` as `prompt_tokens`, and the envelope's
  `total_cost_usd`. The summary line prints `prompt_tokens/run=` and `cost/run=$` for every role session that
  answered in a run, graded or not; `tokens` and `max_overhead_tokens` are unchanged.

**Planned A/B (owner-run, live).** `reviewer` and `security-engineer`, n = 5 each, the fixture in every workspace,
one run with `--omit-claude-md off` and then one with `on`; each runs its probe.

- **Validity.** The pair counts only if the A/B check says VALID: same inputs (fingerprint), same CLI, the off
  arm's probe quoted the file's heading and the on arm's did not. An INVALID arm or pair is discarded and re-run,
  never read as "no loss". The arms run one after the other. An `on` arm whose transcripts show a read of
  `CLAUDE.md` did not measure its absence.
- **Decision.** The field ships on a lens only if the `on` arm still clears `mean - stddev >= 0.8` and its
  pass-rate does not fall below the `off` arm's beyond run-to-run noise. The `prompt_tokens/run` and `cost/run` gap
  is the saving.

Not yet done: `run_skill_evals`'s judge still loads CLAUDE.md, and that is a separate change with its own record
field.

### The A/B, run 2026-11-27, and the decision

The A/B was run on tree `cf429ce` with Claude Code 2.1.331, n = 5, role and judge on `claude-opus-5-5`, and the shipped
fixture as each workspace's CLAUDE.md. The sets were the original ones: 3 cases per lens.

| Lens | `off` (loaded) | `on` (omitted) | Probe | Cost/run off → on |
|---|---|---|---|---|
| reviewer | 1.000 ± 0.000 | 0.986 ± 0.032 | VALID | $0.457 → $0.399 (−13 %) |
| security-engineer | 1.000 ± 0.000 | 1.000 ± 0.000 | VALID | $0.501 → $0.420 (−16 %) |

- **The probes.** Both pairs were VALID: each off arm quoted "Ledgerline — project rules" and each on arm answered
  `NONE`. The probe's own prompt differed by about 3,000 tokens, which is the file. Over whole runs, the
  `prompt_tokens/run` difference moved with turn count, as the round-2 review predicted. For the reviewer it went the
  wrong way (−4,673), so the cost line is the better measure of the saving.
- **The transcript check decided the reviewer.** Four session transcripts in the reviewer's `on` window show a `Read`
  of the workspace `CLAUDE.md`. Two came from the reviewer itself on the design-review case; the other two came from
  the judge. So that arm did not measure the file's absence. By this amendment's own rule, the reviewer is not
  decided and keeps loading CLAUDE.md. A reviewer that goes looking for the project's rules would only move the cost
  to a `Read` anyway.
- **security-engineer drops CLAUDE.md.** Its `on` window has no read of the file. Its `on` arm scored 1.000, the same
  as `off`, which clears both conditions of the decision rule, and the run cost 16 % less. Its definition now sets
  `omitClaudeMd: true`. This covers the delegated security lens only. A project rule the lens needs reaches it in the
  delegation prompt, or it can `Read` the file.
- **Not measured.** Whether the security lens misses a project-specific rule in a real repository. The fixture's one
  security rule, no secret in a log line, already matches the role's own contract.
