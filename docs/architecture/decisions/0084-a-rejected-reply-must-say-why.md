# ADR 0084 — A rejected router reply must say why

Status: Accepted (implemented)
Date: 2026-09-12

## Context

ADR 0083 split `eval.yml` so the weekly cron runs Tier-1. The first dispatch of the new shape was
also the first run in this repository's history where the subscription token was present and the
model-backed step actually executed. It ran for 32 minutes and failed:

```
[architecture]      PASS  recall=1.000 specificity=1.000
[code-review]       FAIL  recall=1.000 specificity=1.000  [8/50 no decision]  (2 prompt(s) unmeasured)
[deep-review]       FAIL  recall=1.000 specificity=1.000  [15/55 no decision] (3 prompt(s) unmeasured)
[develop]           FAIL  recall=1.000 specificity=1.000  [14/50 no decision] (3 prompt(s) unmeasured)
… 17 skills, 7 failing, every one of them at recall 1.000 / specificity 1.000
```

Read that carefully: **the routing is perfect everywhere it was measured.** Every failure is a
measurement failure — between 6% and 27% of router calls returned no decision at all, and where
every call for one prompt came back empty-handed, the prompt is unmeasured and the gate refuses to
score (ADR 0064/0067, which is the correct behaviour and stays).

And the log could say nothing more than that. "No decision" is the conclusion of
`parse_selection`, which rejects a reply for one of six quite different reasons — prose by length,
prose in another script, too many tokens, a negation/acting word, several names at once, no known
name — and the two that matter most need **opposite** responses:

* the router answered like an agent instead of a classifier → a prompt/system problem, and the
  rejection is the signal working;
* the call came back empty → a transport problem, and retrying is right.

A maintainer reading that CI log cannot tell which happened, and the only way to find out was to
pay for another 32-minute run with a debugger attached. This is ADR 0081's finding one layer up:
a rejection that does not say what it rejected cannot be acted on.

## Decision

`parse_selection` keeps its signature and its semantics; the classification moves into
`classify_reply(reply, names) -> Reply(decision, reason, excerpt)`:

* `reason` is one of `INVALID_REASONS` — `empty`, `prose-length`, `prose-non-latin`,
  `prose-tokens`, `negation-or-acting`, `ambiguous`, `unknown-name` — and `""` for a decision;
* `excerpt` is a one-line, 120-character sample of what came back instead.

`PromptRate` carries the reasons and up to two excerpts per prompt; `Tier1Report` aggregates them
into `invalid_reasons` (a tally) and `invalid_excerpts` (up to three). The summary line becomes

```
[develop] FAIL  recall=1.000 specificity=1.000  [14/50 no decision: prose-tokens x11, unknown-name x3]
```

and a failing skill prints its samples underneath, so the CI log carries the evidence. The
diagnostics record the runner writes on a failure carries the same tally, which is what a future
field bundle will contain.

## Consequences

- A Tier-1 failure is now diagnosable from the log alone, without re-running the eval.
- The counts make the two populations separable over time: if `prose-*` dominates, the router
  system prompt or the answer format needs work (ADR 0064 already moved to `--system-prompt` for
  exactly this reason, and the remaining rate says how far that got); if `empty` dominates, the
  transport does.
- Nothing about the gate's strictness changes. An unmeasured prompt still fails the skill — a
  number computed from half the samples is weaker evidence, and ADR 0067 settled that.

## What this deliberately does NOT do

**No retry is added yet.** The plan this ADR came from included "retry the transport class", and
reading the runner while implementing showed that half of it already exists: `claude_cli_runner`
retries a failed or timed-out call three times with backoff and *raises* if it never succeeds — so
a broken call cannot reach the parser as "no decision" at all. What can reach it is a call that
succeeded and returned nothing (an empty `result`, a turn cap hit mid-answer), and the frequency of
that is exactly what this ADR makes visible and nobody can yet state. Adding a retry now would be
guessing at a distribution one CI run away from being known — the failure mode this whole batch of
ADRs is about. Measure, then decide.
