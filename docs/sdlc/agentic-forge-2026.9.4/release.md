---
type: release
feature: agentic-forge-2026.9.4
status: final
version: 2026.9.4
date: 2026-09-14
changelog:
  - "Measured: the SessionStart note from 2026.9.3 is the fix, and now there is a number for it (ADR 0092). Paired on a stand that finally had work on it: note OFF **48/84 = 0.571**, note ON **78/84 = 0.929**, z = 5.87 — thirty prompts from two sentences. The 36 note-off misses were each asked why and answered *\"momentum\"*, *\"no deliberate choice\"*, *\"never paused to route\"*, *\"I should have used it\"*. Not one cited cost; not one declined. The model does not know and decline — it never asks itself the question, and the note is the one thing that puts it in context before the momentum starts"
  - "Fixed: the activation eval had nothing to work on (ADR 0090). One neutral question put to all 36 misses of the first run got the same answer 36 times — the working directory was empty. Every earlier Tier-1b number (0.333 → 0.560 → 0.655) had been measured on one shared temp dir for 84 prompts. Each prompt now runs in a fresh copy of the spine fixture: a git history, a feature branch with a committed change, an unstaged edit, the SDLC docs, a plan, a blog post, a page, a knowledge vault"
  - "Measured: the first honest activation baseline, **78/84 = 0.929** (ADR 0091), then **79/84 = 0.940** on the polished stand (ADR 0093). `code-review`, read for three ADRs as \"the model knows and declines\" at 0.000, is 5 of 5 the moment there is a diff to review. The four skills three ADRs were built around never had a problem; the stand did"
  - "Changed: `--min-activation` gates the rate **pooled over the run**, and CI's `tiers: activation` runs it at **0.80** (ADR 0093). At 4-9 prompts a skill, no per-skill floor is both a gate and true: 0.6 flakes one healthy run in seven and catches a halved skill a third of the time. Pooled over 84 prompts, 0.80 sits five sigma under the baseline, fails the note-off regime with certainty, and catches a drop to 0.75 seven runs in eight"
  - "Added: the pre-router (ADR 0089) — a `UserPromptSubmit` hook that names the clearly-matching skill in the prompt's own context, deterministic, no model call. **Ships OFF** (`pre_router.enabled`): its measured lift was inside single-run noise on a stand ADR 0090 then found empty, and the honest baseline left it nothing to fix"
  - "Changed: **a session that never ran is undetermined** — in every tier, in the PR watcher, in the connectors (ADR 0093/0094). A usage limit, an API error, a `--max-turns` hit, a timeout: the runner reads the envelope and says so instead of scoring a zero, a miss, a rejection or \"healthy\". A gated run with more than 10% of its sessions undetermined fails **as a run**, not as the component"
  - "Fixed: the whole plugin swept for the three shapes those thirteen ADRs turned out to be (ADR 0094) — ~50 verified findings, 9 high. The PR watcher posted a canned \"rejected\" reply publicly when its fixer session hit a usage limit; two hook warnings had been written to a channel Claude Code discards; the stack packs the roles are told to apply were unreachable by the roles; a Tier-2 run wrote into the operator's real `~/Downloads` and packed their real `~/.claude`; ten gated contracts asserted \"no existing test is weakened\" over an empty fixture list; `rm -rf` of a path inside the user's own home was blocked on every Linux CI runner"
  - "Added: `hooks-py39` in CI — `dev/hook_smoke.py` compiles every shipped file, imports every hook-reachable module and runs every hook under **CPython 3.9** with nothing installed. Hooks run under the user's bare `python3`, which on a stock macOS is 3.9.6, and a hook that cannot start fails **open** and silent. The floor was assumed for months; it is now tested"
breaking:
  - "`tier2_quality.runs` is required in `schemas/evals.schema.json` (minimum 5). An out-of-tree component contract that omits it now fails Tier-0. All 27 in-tree contracts already set it"
  - "The `ops` seams raise `ops.SourceUnavailable` instead of degrading to `[]`. Anything calling `active_alerts` / `recent_deploys` directly must handle it — `rollout_health([], [])` reported \"healthy\", which is how a rate-limited `gh` became a green deploy digest"
  - "`AGENTIC_FORGE_SKIP_TEST_GATE` is now a boolean like every other switch: `0` and `false` **keep** the commit gate. Any non-empty value used to disable it"
---

# Release 2026.9.4

2026.9.3 shipped two sentences and a number that turned out to be measured on nothing. This
release is what happened when each instrument was checked before the thing it measured: the note
earned its number honestly, the eval got a stand, the gate got a defensible floor — and then the
same three defect shapes were found everywhere else in the plugin and fixed in one pass.

## The note is the fix, and now that is a measurement

The first Tier-1b runs had every prompt in one shared empty temp directory. One neutral question
put to all 36 misses came back the same 36 times: *there was nothing here to review*. Every
activation number the project had — 0.333, 0.560, 0.655 — was measuring an empty room (ADR 0090).

Rebuilt, with a fresh copy of the spine fixture per prompt, the first honest baseline is **78/84 =
0.929** (ADR 0091). `code-review`, at 0.000 on the empty directory and read across three ADRs as
"the model knows the skill and declines it", is **5 of 5** the moment there is a diff. The four
skills that whole line of work was built around never had a problem. The stand did.

Which left the note itself unmeasured, so it got an off switch and the run was repeated with one
variable changed (ADR 0092):

```
                     note ON      note OFF
pooled               78/84 0.929  48/84 0.571     Δ = −0.357   z = −5.87
the "hard four"      17/19 0.895   6/19 0.316
```

Thirty prompts out of eighty-four, from two sentences injected once per session. And the 36
note-off misses, each asked why, say what the shape actually is:

> *"I just started reviewing directly out of momentum … without pausing to route the task"*
> *"there was no deliberate choice … it was an oversight"*
> *"Honestly? No principled reason — it was a mistake on my part."*

Not one says the skill was too expensive. Not one declines. The model does not weigh the skill and
reject it; **it never asks itself the question**, and the note is the one thing in context that
puts the question there before the first obvious tool call.

## A gate that is one number

`--min-activation` now gates the rate **pooled over the run** rather than per skill (ADR 0093). A
skill has 4-9 trigger prompts, and at that n there is no per-skill floor that is both a gate and
true: loose enough not to flake (0.5) catches a halved skill one time in three; tight enough to
catch it (0.75) fails a healthy plugin every other run. Pooled over 84 prompts the same true rate
is a different instrument — 0.80 sits five sigma under the baseline, fails the note-off regime with
certainty, and catches a drop to 0.75 seven runs in eight. The per-skill lines stay as the lens.

The run that set the floor also taught the rule that runs through the rest of this release: two
`research` "misses" were 300-second timeouts whose partial transcript the runner had thrown away —
both sessions had invoked the skill before the kill. A re-run scored `research` 5/5.

## The same three shapes, everywhere else

Read together, ADRs 0081–0093 are not thirteen defects. They are three (ADR 0094):

1. **A verdict from nothing** — a session that never ran, a timed-out subprocess, an errored `gh`
   call, an empty list, scored as a miss, a failure, a rejection, or "healthy".
2. **A message to nobody** — a warning written to a channel that discards it, a crash recorded only
   behind an opt-in that is off.
3. **A stand that presupposes what it does not carry** — a prompt about "this incident" with no
   incident, an assertion about "no existing test" over an empty fixture list, a role told to load
   a skill it cannot invoke.

So the whole plugin was swept for those three shapes: fifteen classes across six areas, every
candidate traced through its call path, the guardrail ones executed against the live classifier.
About fifty findings survived verification, nine of them high. What they were:

- **The PR watcher posted a canned answer for a session that never happened.** A fixer run that hit
  the account's usage limit was scored *rejected*, and "No change made — may be a discussion point"
  went publicly onto the reviewer's thread, on every actionable thread of every queued PR. It is
  now *undetermined*: nothing is posted, the thread waits for the next poll.
- **Two guardrail warnings had been speaking into a discarded channel** — the merge preflight and
  the subagent soft cap wrote to stderr and exited 0, which Claude Code shows to nobody. And every
  hook's crash was "recorded" through a diagnostics log that is off by default, so a dead guardrail
  on a default install looked exactly like a healthy one.
- **The standards the plugin advertises were unreachable by the roles meant to apply them.**
  `engineering-standards` and the nine `*-patterns` packs are off-listing — uninvocable by name —
  while `develop`, `software-engineer` and `qa-engineer` were told to "load" them by name, with no
  path. They are now read by file path; a live `develop` session reads both from disk before
  delegating.
- **A Tier-2 eval run wrote into the operator's real `~/Downloads`** and packed their real
  `~/.claude` transcripts and settings into graded output — by contract, since the case asserted
  it. It now runs against a seeded fake home.
- **Ten gated contracts asserted "no existing test is weakened, skipped, or deleted" over an empty
  fixture list**, which passes on nothing. They now seed a manifest, a source file and a test.
- **`rm -rf` of a path inside the user's own home was blocked as a system directory** on every
  Linux CI runner, and `chmod -R u+x` counted as world-permissive; a `git push` inside a heredoc or
  a `grep` argument triggered the 110-second commit gate.

The fix is one set of primitives rather than one patch per sighting: `hook_notice` and `hook_crash`
for anything a hook needs to say; `SessionUndetermined` and a 10% cap for anything that consumes a
model session; `SourceUnavailable` for anything that consumes an external source; a `tree/` fixture
layout for anything a contract asserts about.

## The floor the field actually runs on

Hooks execute under the user's bare `python3`. On a stock macOS that is CPython 3.9.6 — the
interpreter in both field bundles — while the repo's own tooling requires 3.11. Moving the hooks
"to the latest" would make them fail to parse on a stock Mac, and a hook that fails to start fails
**open**: the guardrail is silently gone and nothing says so. So 3.9 stays the floor for
hook-reachable code, and `ci.yml` now proves it instead of assuming it — `dev/hook_smoke.py`
compiles every shipped file, imports every hook-reachable module and runs every hook on a minimal
payload under 3.9 with nothing installed. A new hook without a smoke payload fails the test.

## The stand that carries its own prompts reads 0.988

The re-baseline was run on the released tree, because this release changed the stand as much as it
changed the plugin: eight skills' trigger prompts now carry their referent, the fixture seeds a
knowledge vault, and every phase skill has a branch for an input that is not there.

```
1.000  architecture code-review deep-review deploy-watch develop incident-response knowledge
       marketing plan product qa-test-strategy release repo-onboarding research
       security-review skill-factory                                        (16 skills)
0.750  ux-design 3/4

pooled 83/84 = 0.988      mean of rates 0.985      (0.929 → 0.940 → 0.988 across the three stands)
```

The single miss is a reading of the prompt, and a defensible one:

> *"I read 'what ARE the accessibility requirements?' as a lookup question about existing docs
> rather than a request to design them"* — `ux-design`

Four things moved at once between this run and ADR 0093's 79/84, so **this is a new baseline of
record, not a measured lift attributable to any one of them**: the prompts, the descriptions, the
absence branches, and a scorer that no longer credits a bare built-in name. What it does settle is
that the remaining gap is the eval's reading of one question, not the model's routing.

**The floor stays at 0.80.** It was not chosen against the current value — it was chosen to survive
model drift: at a true rate of 0.90 a floor of 0.85 flakes one run in fourteen, and this gate runs
on whatever `EVAL_MODEL` is. One run at 0.988 is not a reason to tighten a gate whose job is to
catch a regression, and tightening on a single sample is the over-fit this whole series has been
correcting.

## What was deliberately not done

- **The description rewrite is cancelled** (ADR 0091), not deferred. It was aimed at a reason one
  session in eighty-four gave — that a five-way fan-out over a 24-line document is disproportionate
  — and that session was right.
- **The Stop-hook was not built** (ADR 0091). A guardrail that blocks a session exists to recover a
  systematic failure; 0.929 with one preference miss is not one.
- **The pre-router ships off** (ADR 0089/0091). Its code and its leave-one-out contract stay under
  Tier-0; its measured lift was inside single-run noise, on a stand that was later found empty.
- **No skill was renamed.** The listing budget has no headroom and the data has never shown a
  built-in taking a request from us.

## Verification

- Tier-0 clean: `validate.py`, `ruff`, `mypy` (now including the shipped `plugin/bin` CLIs), 1748
  tests, coverage 95.6%.
- `dev/hook_smoke.py` OK under CPython 3.9.6 and 3.14 — 46 files compiled, 10 hook-reachable
  modules imported, 8 hooks run.
- **Tier-1 routing on the released tree: 17/17 at recall 1.000 / specificity 1.000**, 814 router
  calls, zero no-decision calls. Descriptions changed for four skills and trigger prompts for
  eight, so the whole suite was re-run rather than the touched skills alone.
- **Tier-1b activation on the released stand: 83/84 = 0.988 pooled**, sixteen of seventeen
  skills at 1.000, one miss (see below).
- Live probe: a `develop` session reads `engineering-standards` and `python-patterns` from disk
  before delegating — the packs were unreachable before this release.
- Tier-2 and Tier-3 were **not** run for this release (~360 sessions, on demand per ADR 0083).
  Their fixtures and prompts changed materially here, so the next `tiers: all` dispatch is their
  first pass on the new stand.
