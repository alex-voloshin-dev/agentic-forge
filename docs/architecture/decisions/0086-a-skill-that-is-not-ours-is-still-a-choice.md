# ADR 0086 — A skill that is not ours is still a choice

Status: Accepted (implemented)
Date: 2026-09-12

## Context

ADR 0085 took the Tier-1 run from six failing skills to one, and cut discarded router calls from
65 to 9. The one that remained, with its excerpts:

```
[deep-review] FAIL  recall=1.000 specificity=1.000  [5/55 no decision: unknown-name x5]
    no-decision sample: The `run` skill matches best. run
    no-decision sample: The `run` skill matches this request. `run`
```

The unmeasured prompt is a **should-not-trigger** one: *"Run the app and screenshot it"*. The
router answers `run` — Claude Code's own built-in skill (`run: Launch and drive this project's app
to see a change working`) — which is exactly right. `deep-review` was correctly not chosen. But
`run` is not an agentic-forge skill, so it is not in the listing the harness renders, so the parser
reports `unknown-name` and throws the call away. Five of five, so the prompt is unmeasured, so the
skill fails.

For the fifth time in this sequence (ADRs 0082–0085), the router is right and the measurement does
not know how to say so.

## Decision

A terminal, standalone token that is **skill-shaped** (`^[a-z][a-z0-9-]{1,39}$`) but not in the
listing is a decision — `OTHER`, "the router chose something, and it was not the skill under test".
It is never a hit for any of our skills. `selection_rate` treats it as a valid call that missed the
target.

The consequence is asymmetric, and the asymmetry is the safety property:

| prompt kind | an `OTHER` reply counts as | direction |
|---|---|---|
| should-trigger | a **miss** — recall goes down | strict |
| should-not-trigger | a correct non-selection — specificity holds | lenient |

A degenerate router that answers with a plausible-looking word every time scores `OTHER`
everywhere, gets recall 0.0 on every skill, and fails the gate. The lenient half cannot be gamed
without the strict half collapsing.

The shape check plus ADR 0085's position rule (terminal, after a sentence boundary) keep this away
from the mining failure ADR 0064 was written against. "…I would not run" still yields nothing; a
bare number or a punctuation-laden fragment is not a name.

Stated plainly, the trade: specificity becomes easier to *measure* — such calls were previously
discarded, now they count. That is accuracy, not leniency. The router did not select
`deep-review`; pretending the sample does not exist was the inaccurate reading.

## What this exposed, and is not fixed here

The eval renders **only agentic-forge's listing** into the router's system prompt. The router runs
inside a real Claude Code, whose built-in skills — `run`, `code-review`, `simplify`, `init`,
`security-review` — it also knows about and will choose. So Tier-1 measures routing in an
environment that does not exist in production: in a live session those built-ins sit beside ours
and compete for the same requests.

That connects directly to the field finding in ADR 0081 — 183 `Agent` calls against 3 `Skill`
calls over 27 days — and offers a second, cheaper hypothesis than the one recorded there. Part of
"the spine skills never fired" may be *the built-in listing winning*, not a repository instruction
pre-empting the router: `code-review` (ours) versus `code-review` (built-in) and `security-review`
versus `security-review` are literal name collisions. The eval cannot see that today.

The measurement that would settle it is a Tier-1 condition rendering the built-in skills into the
listing alongside ours. It is recorded in the roadmap next to ADR 0081's competing-instruction
condition; both should run before anyone edits a description over either hypothesis.

## Alternatives considered

- **Add Claude Code's built-in skill names to the parser's known set.** Rejected: the harness would
  have to track another product's skill list, and a stale copy would silently turn a correct `run`
  back into `unknown-name`. The shape rule needs no list.
- **Render the built-ins into the listing now, as part of this change.** Rejected as scope: it
  changes what every Tier-1 number means, deserves its own measurement and ADR, and the current
  failure is fixed without it.
- **Keep discarding, and rewrite the should-not-trigger prompt to avoid `run`.** Rejected: the
  prompt is a good one precisely *because* a real skill wants it. Editing evals to fit the parser is
  the wrong direction.
