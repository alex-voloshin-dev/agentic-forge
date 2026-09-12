# ADR 0087 — Under the built-in listing, five of seventeen pass

Status: Accepted (implemented)
Date: 2026-09-12

## Context

ADR 0086 recorded a hypothesis and asked for a measurement: Tier-1 renders only this plugin's
listing, while a live Claude Code session shows its built-in skills beside ours — two of them
colliding with ours by exact name. The measurement ran the same day.

| skill | ours alone | **with the built-ins** | discarded |
|---|---|---|---|
| security-review | 1.000 | **0.000** | 0 |
| code-review | 0.960 | **0.200** | 3 |
| incident-response | 1.000 | **0.200** | 0 |
| deploy-watch | 1.000 | 0.257 | 1 |
| marketing | 1.000 | **0.378** | 0 |
| deep-review | 1.000 | 0.450 | 2 |
| qa-test-strategy | 1.000 | **0.600** | 0 |
| plan / ux-design | 1.000 | 0.650 | 3 / 1 |
| skill-factory | 1.000 | 0.700 | 3 |
| release / develop / knowledge | 1.000 | 0.800 / 0.840 / 0.840 | 1 / 1 / 2 |
| repo-onboarding / architecture / research / product | 1.000 | 0.900 / 0.920 / 0.920 / 0.960 | — |

**Five of seventeen pass**, against seventeen of seventeen an hour earlier. Specificity is 1.000
throughout — under the condition a bare built-in name scores as `OTHER`, a correct non-selection.

Three different things are in that table, and the log could separate only two of them.

1. **Exact-name collisions.** `security-review` at 0.000 and `code-review` at 0.200 with no
   discarded calls: the router answered the bare name — the built-in — every time. One excerpt says
   so in words: *"I've invoked the `/code-review` skill to review this branch's diff."*
2. **Clean losses to something.** `incident-response`, `marketing`, `qa-test-strategy` lost with
   zero discards. The router chose validly and chose something else — and the log cannot say what.
   ADR 0086 made a wrong-but-valid choice a decision (`OTHER`); ADR 0084 sampled only *invalid*
   replies. A decision that was not the target went uncounted by name. `marketing` at 0.378 is a
   number with no cause attached.
3. **A parser blind spot the namespace created.** Excerpts read `Skill(agentic-forge:plan)`,
   `Skill(agentic-forge:product)`, `Skill(agentic-forge:deep-review)`: the router answering
   correctly in the tool-call spelling the namespaced listing invited. Rejected as `unknown-name`.
   Seven skills lost calls to it; it does not account for their numbers on its own (`deep-review`
   sits at 0.450 with two discards), but it muddies every one of them.

A fourth thing surfaced at the same time. The dispatch that ran this condition also launched the
whole Tier-2/Tier-3 suite — `quality.if` excluded `trigger-only` rather than listing what it
accepted, so a new option elsewhere widened it. The run was cancelled once the condition step had
finished; the quality job had by then consumed ~45 minutes of the subscription for nothing.

## Decision

1. **Every should-trigger loss names its winner.** `Reply` carries `choice` — the name the router
   actually gave — even when the decision is `OTHER`; `selection_rate` collects the non-target
   choices; the report tallies them as `lost_to`; a failing skill prints
   `lost should-trigger calls to: design x12, none x3`, and the diagnostics record carries the same.
   Losses on should-NOT-trigger prompts are not counted: there, a non-target *is* the right answer.
2. **The tool-call spelling is the name it wraps.** `Skill(agentic-forge:plan)` reads as
   `agentic-forge:plan`; `/code-review` as `code-review`. Under ADR 0085's position rule, so still
   terminal and standalone.
3. **The quality job runs on a positive list** — `tiers == 'all'` or the `eval` label. Shipped
   separately the moment it was found (PR #42), recorded here.
4. **No description and no name is changed.** Renaming `code-review` and `security-review` is the
   obvious candidate and precisely why it waits: the attributed re-run will say whether the other
   twelve losses are the same kind of thing or several different ones, and a rename decided before
   that is a guess with the listing budget.

## Consequences

- The next run of the condition is interpretable per skill: which built-in wins, how often, and
  whether `none` — the router declining our whole listing — is part of the loss.
- This is the first direct evidence for what the field bundles showed: 183 `Agent` calls against 3
  `Skill` calls (ADR 0081) is at least partly the built-in listing winning, not a repository
  instruction pre-empting. The competing-instruction condition stays on the roadmap; it is no longer
  needed to explain most of the gap.
- The strict reading of a bare collided name (as the built-in) is how Claude Code itself resolves
  it — a plugin skill is invoked as `agentic-forge:security-review`. So 0.000 is not an artifact
  of scoring; it is what a user asking for a security review would get.

## Corrected the same day: the attributed run

Decision 1 ran, and it overturned the reading in *Context* §1.

```
[deploy-watch]       FAIL 0.200   lost should-trigger calls to: deploy-watch x28
[incident-response]  FAIL 0.050   lost should-trigger calls to: incident-response x19
[marketing]          FAIL 0.511   lost should-trigger calls to: marketing x22
[security-review]    FAIL 0.050   lost should-trigger calls to: security-review x19
[code-review]        FAIL 0.240   lost should-trigger calls to: code-review x15, review x3, security-review x1
```

`deploy-watch` lost to `deploy-watch`. No built-in of that name exists; the only `deploy-watch`
in the listing is `agentic-forge:deploy-watch`. The router chose ours and answered with the bare
name — and it did that for **every** skill, namesake or not. The strict reading in *Consequences*
("0.000 is not an artifact of scoring") was wrong: a bare `security-review` is exactly as likely to
be ours as a bare `deploy-watch` is, which is to say, it is ours. The arithmetic confirms it line
by line — `incident-response`: 1 hit + 19 bare = 20 = 4 prompts × 5; `marketing`: 23 + 22 = 45 =
9 × 5; every skill returns to 1.000 except `code-review`, which keeps four real losses (`review`
×3, `security-review` ×1) and lands near 0.84.

What is real in the run, then:

- **Not one loss to an actual built-in.** No `design`, `run`, `simplify` or `loop` appears as a
  winner for any skill. Hypothesis (b) of ADR 0086 — the built-in listing wins *by meaning* — is
  not supported by this data. The weight goes back to ADR 0081's (a), the competing repository
  instruction, for the field gap.
- **The name collision is unmeasurable by this method.** A bare `code-review` says nothing about
  which entry the router meant, because it never writes the prefix for anyone. Which one Claude
  Code *invokes* on a bare name is a product behaviour, observable only in a live session — and the
  first field bundle already hints at the answer: its recorded invocations are
  `agentic-forge:deploy-watch`, `agentic-forge:develop`, prefixed. The model prefixes when it
  invokes, and abbreviates when it classifies.

So the scoring is corrected: under the condition a bare own name is a **hit**, and a bare hit on
a name a built-in also owns is counted as ours *and reported* — `[15 hit(s) under a bare name a
built-in also owns — ambiguous]` — so the collision stays visible in the line rather than vanishing
into a green number. The rename question stays open, and it is now the product check that decides
it, not another eval.

## Alternatives considered

- **Rename the two collided skills now.** Rejected for this ADR: it is the likely outcome, but the
  attributed run costs one CI dispatch and tells whether it is the *only* fix needed.
- **Sample every reply, not only losses.** Rejected: a tally of winners is what the question
  needs; full samples are volume without more signal.
- **Score a bare collided name as ours.** Rejected: it would measure a resolution rule Claude Code
  does not use, and hide the one loss this whole exercise was built to find.
