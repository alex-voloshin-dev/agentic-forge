# 0064 — Tier-1 measurement integrity: a non-answer is not a routing decision

Status: Accepted — **implemented**. Corrects the measurement contract of
[0016](0016-tier1-trigger-runner.md) / [0026](0026-tier1-mean-routing-rate.md) (the Tier-1
runner and its mean-rate metric). No skill, description, or threshold changed.

## Context

A Tier-1 run on six unchanged skills produced numbers that would not stabilise. `product`, measured
three times against a **byte-identical** listing within one hour, scored recall **0.800**, then
**1.000**, then **0.720**; `ux-design` ranged 0.750 → 1.000 → 0.950. The runbook's known
throttling failure mode was the obvious suspect, and the first conclusion drawn was exactly that.

It was wrong. A diagnostic that captured the **raw** router reply for every miss found, over 50
calls, **zero empty or truncated replies** — no throttling. What it found instead was one reply of
5637 characters: prose, in the session's ambient language, reasoning about the repository's
sandbox and its ADR index. The model had not routed anything; it had answered a different question
entirely.

Two independent defects turned that into a number:

1. **`parse_selection` mined the prose for a decision.** It scanned any reply left to right for the
   first known skill name — so an essay that happened to contain the word "knowledge" was scored as
   a vote for the `knowledge` skill. "The router never answered" became "the router chose wrong",
   silently.
2. **The router call was not hermetic.** `claude_cli_runner` passes the router instruction via
   `--append-system-prompt`, i.e. *on top of* Claude Code's default agent system prompt. Primed as
   an agent, the model explores and explains instead of emitting one token.

The corruption is **asymmetric**, which is what made it so hard to see: an off-format reply almost
never names the skill under test, so it depresses `recall` — but it almost never names a *neighbour*
skill either, so `specificity` stays at a perfect **1.000**. Every failing run in this episode
reported exactly that signature, and it reads like a clean, believable result.

The cost of not fixing it is concrete: the next step from "recall 0.720" is editing `product`'s
description to chase the number — spending the router's ~1% listing budget, which has no headroom,
to repair a defect that was never in the description.

## Decision

1. **A reply that is not an answer is `INVALID`, not a decision.** `parse_selection` returns a new
   `INVALID` sentinel — distinct from `"none"`, which remains a *real* routing decision ("no skill
   fits") — when the reply exceeds `MAX_ANSWER_TOKENS` (12) or names nothing known. Prose is never
   mined for a skill name.

   The token cap is the discriminator because the answer format demands one name: a conforming
   reply is `research`, `` `research` ``, or "The answer is: `research`." — all far under the cap —
   while an off-format reply is paragraphs.

2. **Invalid calls leave the denominator.** `selection_rate` returns `PromptRate(rate, invalid,
   runs)` and computes the rate over *valid* calls only. A call that produced no decision is
   **missing data**; averaging it in as a miss understates recall by exactly the amount of noise in
   the channel.

3. **A prompt whose every call was invalid is `unmeasured` — and fails the gate.** Its rate is
   `None`, not `0.0`: reporting zero would fabricate a routing failure out of a measurement
   failure. It is excluded from the means and added to the report's reasons, so the run cannot pass.
   *Not measuring something is not the same as it passing — and not the same as it failing either.*

4. **Discarded calls are always reported**, pass or fail: `summary_line` appends
   `[N/M calls returned no decision]`. A green number computed from half the samples is weaker
   evidence than one from all of them, and hiding that is the silent-cap antipattern.

5. **The router gets its own system prompt.** `claude_cli_runner(replace_system=True)` uses
   `--system-prompt` (replace) instead of `--append-system-prompt`, and `dev/run_tier1_evals.py`
   passes it. Role evals (Tier-2) keep appending — a role *is* an agent and should inherit the agent
   prompt; a router is a classifier and should not.

## Limits, stated honestly

- **This does not make the call fully hermetic.** The CLI's user-level `CLAUDE.md` auto-discovery
  still applies; only `--bare` disables it, and `--bare` forces `ANTHROPIC_API_KEY` auth, which
  would break the subscription-billed path the runbook recommends. So decision 5 *reduces* the
  incidence; decisions 1–4 are what make the metric trustworthy regardless of incidence.
- **The historical numbers recorded in this repo were measured through the old parser.** They are
  not retroactively corrected, and a recorded Tier-1 figure from before this change should be read
  as "≥ this, possibly higher".
- The 12-token cap is a heuristic. It is deliberately generous (a bare answer is 1–5 tokens) so it
  cannot reject a legitimate terse reply; a pathological one-line off-format answer that names a
  skill would still slip through.

## Alternatives considered

- **Re-run when the quota is calm (the runbook's existing advice):** insufficient — it was tried, and
  the "calm" run was the *worst* of the three. The advice addresses throttling, which this was not.
- **Retry an invalid call instead of dropping it:** rejected for now — it hides the rate of channel
  corruption behind a retry loop, and the whole point of this ADR is that the corruption must be
  *visible*. The count is reported instead; a retry can be layered on later if the rate is high.
- **Count invalid as a miss (the old behaviour, made explicit):** rejected — that is the bug.
- **`--bare` for full isolation:** rejected — the auth cost (see Limits) outweighs the benefit given
  decisions 1–4 already contain the damage.
- **Loosen the thresholds because the metric is noisy:** rejected — the thresholds were never the
  problem; the channel was.

## Consequences

- Tier-1 can no longer silently convert a broken call into a routing verdict, so a description edit
  can only be triggered by evidence that the router actually made a wrong choice.
- A run in a degraded environment now **fails loudly as unmeasured** instead of reporting a plausible
  low number — the failure is legible as "we could not measure this", which is the honest outcome.
- Every Tier-1 report gains a visible discarded-call count, so the strength of the evidence is on the
  face of the result.
- `selection_rate`'s return type changed from `float` to `PromptRate`; callers inside the runner and
  its tests were updated. Public API of the CLI is unchanged.
