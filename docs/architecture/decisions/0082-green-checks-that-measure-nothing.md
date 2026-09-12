# ADR 0082 — Green checks that measure nothing

Status: Accepted (implemented)
Date: 2026-09-12

## Context

The second field bundle of 2026-09 is shaped differently from every one before it: two repositories
side by side — this plugin developing itself, and `softico-web`, an unrelated production Next.js
project the plugin works on but did not author. 3,246 tool calls here, 13,585 there.

Read together, the two halves say the same thing three times. Something reports success; nothing was
measured.

### 1. The weekly eval cron has been green and blind for months

`CLAUDE.md` states that "a weekly CI cron re-runs Tier-1 so a routing regression surfaces". The last
six scheduled runs of `eval.yml` all finished **success in 23-32 seconds**. Inspecting the steps:

```
success  Skill Tier-1 wiring (dry-run, no auth)
skipped  Skill Tier-1 trigger (subscription via claude)
skipped  Agent Tier-2 quality       skipped  Skill Tier-2 quality
skipped  Spine Tier-3 E2E           skipped  Domain Tier-3 chains
```

Every model-backed step is gated on `if: env.CLAUDE_CODE_OAUTH_TOKEN != ''`, and the secret is not
set on the repository. So the guard ran its wiring checks, found the contracts resolvable, and
reported the same green tick it would report for "recall is above 0.9".

### 2. What that guard would have caught

The plugin's own diagnostics log, from local runs on 2026-07-15 and 07-25/26:

| component | recorded | threshold |
|---|---|---|
| `tier1-eval:ux-design` | recall 0.750 | 0.900 |
| `tier1-eval:product` | recall 0.720 – 0.840 (6 records) | 0.900 |
| `tier1-eval:research` | recall 0.800 / 0.840 | 0.900 |
| `tier1-eval:marketing` | recall 0.822 | 0.900 |
| `skill-eval:deep-review` | pass-rate lower bound 0.771 / 0.750 | 0.800 |

These are the same doc-phase skills that ADR 0081 recorded as never triggering in the field (183
`Agent` calls against 3 `Skill` calls over 27 days). That ADR said the hypothesis needed measuring
before anyone touched a description. The measurement existed already — in a log nobody reads,
because the CI that was supposed to surface it could not run.

Note what the diagnostics channel can and cannot say: it records **failures only**. A passing run
writes nothing, so the last recorded number is not the current number.

### 3. The gate was off on the machine that develops the plugin

78 of this repo's 96 diagnostic records are one fail-open: `FileNotFoundError: [Errno 2] No such
file or directory: 'python'`, gate `python dev/validate.py`. This host has no `python` at all —
only `python3`, the modern macOS/Homebrew arrangement. `choose_gate` writes the validator's
interpreter as a bare `python`, so the Tier-0 gate failed open on every commit for the window.

ADR 0081's project-first resolution happens to fix this repo, because a `.venv/bin/python` exists
here. It does not fix a repo without a virtualenv, which is most of them.

### 4. The coverage self-check invents holes and hides real ones

ADR 0058 added a coverage disclosure so a silently non-writing hook is visible from a bundle. In
`softico-web` it reported **"9/12 — 3 MISSED (a hook may not have logged them)"**. No hook failed.
The audit log there physically retains **2026-08-22 .. 09-04** — thirteen days, after three
rotations discarded 17 MB — while the transcripts it is compared against go back months. The three
"missed" sessions are sessions rotation deleted.

The same check called this repo **"2/2 — complete"** while ten sessions sat in its audit log: only
three transcripts survive on disk here. The check compares two collections with different retention
policies and reports the difference as a hook failure, in whichever direction the difference falls.

### 5. A slow lint turns the gate off, silently

`softico-web`, 2026-08-18: `gate fail-open (infra): TimeoutExpired: Command '['npm', 'run',
'lint']' timed out after 110 seconds`. A whole-repo eslint on a large Next.js app does not fit the
gate's budget, and the budget is not a free parameter — the hook itself is capped at 120 s in
`hooks.json`. ADR 0081 made this speak up, but with the wrong advice: it tells the operator to
install the tool, which is already installed and working.

## Decision

1. **A scheduled eval run fails when it cannot measure.** `eval.yml` gains a first step that exits
   1 on `schedule` if `CLAUDE_CODE_OAUTH_TOKEN` is absent, naming the two commands that fix it.
   `workflow_dispatch` and the PR label still degrade to wiring-only, which is their purpose. Every
   run also writes to its job summary which tiers it actually measured, so a green tick that means
   "wiring resolves" cannot be mistaken for one that means "thresholds hold".
2. **`CLAUDE.md` states the condition.** The cron claim now carries "but only while the token is
   set", because a rule that is silently false is worse than no rule.
3. **The gate resolves `python` -> `python3`.** `resolve_gate` gains a small alternative-name table,
   consulted only after the project-local bins and `PATH` have failed.
4. **Coverage is counted inside the retained window.** `session_coverage` takes `retained_since`
   (the oldest record the audit log still holds) and each transcript's last activity; sessions older
   than the window are reported as `outside` ("rotated out"), not as `missed`. A transcript with no
   readable timestamp stays in the denominator — claiming a hole that is not there is the failure
   this check exists to avoid, so ambiguity resolves against alarming.
5. **The timeout gets its own remedy.** A `TimeoutExpired` fail-open says the gate timed out, names
   the hook's own cap as the reason the budget cannot simply be raised, and points at scoping the
   lint to staged files or gating in CI.

## Consequences

- The repository's Monday cron will fail until the token is set. That is the honest state of the
  world: right now nothing above Tier-0 is measured on a schedule. The failure message carries the
  fix (`claude setup-token`, then `gh secret set`).
- Coverage lines get longer when rotation has eaten history, and the `outside` count makes the
  audit log's real retention visible in the same sentence. Combined with ADR 0081's archives, a
  future bundle can say "rotated out, and here is the archive".
- `_read_transcript_sessions` now returns a 4-tuple. It is internal, with one caller.
- The alternative-name table is deliberately one entry. It is not a general "try things until
  something runs" mechanism: `python`/`python3` is a specific, known naming split, and anything
  broader would make the gate's behaviour unpredictable.

## The measurement, taken

Before deciding anything about the four skills, Tier-1 was re-run against the live listing —
`--runner claude --model claude-opus-4-8`, five runs each, 2026-09-12:

| skill | July record | now |
|---|---|---|
| `marketing` | recall 0.822 | **1.000** recall / 1.000 specificity — PASS |
| `product` | recall 0.720 – 0.840 | **1.000** / 1.000 — PASS |
| `research` | recall 0.800 / 0.840 | **1.000** / 1.000 — PASS |
| `ux-design` | recall 0.750 | **1.000** / 1.000 — PASS |

So **no description is re-tuned**: all four are well above the bar today. The July failures were
real when recorded and were fixed in passing by the description work of the 2026.7.x releases
(ADR 0056's adoption round) — and nobody could have known, because a passing run writes no record
and the CI that would have re-measured was skipping the step.

That result also sharpens ADR 0081's open question. Trigger recall is **1.000** for exactly the
skills that did not fire in 27 days of field work. The descriptions route correctly when the router
is asked; in the field it evidently was not asked. So the remaining explanation is the one ADR 0081
guessed at — a standing project instruction that is already in context, against a skill that must
first be chosen — and the eval that would reproduce it is a Tier-1 condition carrying a competing
instruction, not a better description. That stays on the roadmap.

Still unmeasured from this bundle: `deep-review`'s Tier-2 (0.771 / 0.750 against 0.800, recorded
twice on 2026-07-26). It is the most expensive eval in the pyramid — a full coding session per case
per run — so it is left for a deliberate run rather than folded into this batch.

## Alternatives considered

- **Set the token in CI as part of this change.** Rejected — it is the user's subscription
  credential; the workflow can demand it, but committing it is theirs to do.
- **Make the scheduled run skip silently but open an issue.** Rejected: more machinery, and a
  failing check is the notification mechanism the repository already watches.
- **Raise the gate timeout.** Rejected: `hooks.json` caps the hook at 120 s, so the subprocess
  budget cannot exceed it without the whole hook being killed — which fails open anyway, with a
  worse message. Scoping the lint is the real fix and the message now says so.
- **Drop the coverage check.** Rejected: it is the only cross-check the bundle has against its own
  completeness. It needed a window, not a funeral.
