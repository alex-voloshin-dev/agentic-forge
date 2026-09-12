# ADR 0085 — The answer may come last

Status: Accepted (implemented)
Date: 2026-09-12

## Context

ADR 0084 made a rejected router reply say why it was rejected. The very next CI run answered the
question it was built to answer, and the answer was not one of the two anyone expected.

Across 17 skills and ~800 router calls, 65 produced no decision:

| reason | count |
|---|---|
| `prose-tokens` | 31 |
| `negation-or-acting` | 18 |
| `ambiguous` | 7 |
| `unknown-name` | 5 |
| `prose-length` | 4 |
| **`empty`** | **0** |

Zero empty replies — so the transport is healthy and the retry ADR 0084 deliberately did not add
is confirmed unnecessary. But the excerpts show what the other 65 actually were:

```
The user wants a thorough adversarial review of docs. deep-review
The user wants to implement the next step of a plan, which matches the develop skill. develop
This is a Kubernetes/YAML fixing task — it doesn't match any of the available skills' domains. none
The user wants me to route this request, not perform it. develop
```

**The router answered correctly.** It stated one sentence of reasoning and then gave the answer,
and the parser threw the whole reply away — for length (over 16 tokens), or for a word like
`doesn't`, `not` or `review` appearing in the reasoning.

Two of those are worse than a lost sample. The third line is a *correct decline* on a
should-not-trigger prompt, discarded for containing "doesn't". The fourth is a correct
non-selection, discarded for containing "not perform it". The guards were draining specificity
evidence exactly where the router was right.

Six of seventeen skills failed on this, every one of them at recall 1.000 and specificity 1.000 —
the gate reporting a failure about its own measurement, not about routing.

### Why the guards are like that

They are right about the reply they were built for. ADR 0064 found the parser mining a page of
agentic prose for the first skill-like word and scoring it as a vote; ADR 0067 added the script and
negation guards after a Cyrillic reply slipped under the token count. Both defended against
**mining a name out of prose that never stated a decision**. Neither considered the shape where the
reasoning comes first and the decision is stated last, on its own.

## Decision

A reply's **terminal token** is the decision when it is a known skill name (or `none`) **and** it
stands as its own final sentence — preceded by a sentence boundary (`.` `:` `!` `?` `—` `–`
newline) or by nothing at all. `trailing_answer()` implements exactly that, and `classify_reply`
consults it before every prose guard.

The ASCII hyphen is deliberately **not** a boundary: it lives inside half the skill names
(`deep-review`, `qa-test-strategy`, `repo-onboarding`).

This is not a return to mining, and the difference is checkable rather than a matter of degree:

| reply | before | now |
|---|---|---|
| `…which matches the develop skill. develop` | invalid | `develop` |
| `…doesn't match any of the skills' domains. none` | invalid | `none` |
| `This is a deployment question and it isn't deep-review` | invalid | **invalid** |
| `The request mentions research but none of the skills fit research` | invalid | **invalid** |
| `I'll read the plan and then write the code with develop` | invalid | **invalid** |

A name inside the sentence that rejects it is still not a decision. Position and a sentence
boundary do the work that word lists were doing badly.

## Consequences

- 65 discarded calls per run become measurements, and the six failing skills were failing on
  nothing else — so the gate goes green **without a single description edit**. That matters for
  what it says about the previous two months: the routing was never the problem.
- The prose guards keep their job for replies that never state a decision, and `MAX_ANSWER_TOKENS`
  stops being load-bearing for correctly-answering routers. It is now what its comment already
  claimed to be: a coarse ceiling.
- The non-Latin guard yields to a terminal answer. A Cyrillic sentence followed by `. research` is
  a decision; a Cyrillic sentence that merely mentions `research` is still not. Tested both ways.
- Measurements from before this change are not comparable with ones after it — the denominator
  changed. Any benchmark history crossing 2026-09-12 should be read with that in mind.

## Alternatives considered

- **Tighten the router's system prompt instead** (ADR 0064 already moved to `--system-prompt` for
  this reason). Rejected as the primary fix: it reduces how often reasoning appears but cannot
  eliminate it, and a measurement that depends on the model never thinking out loud is brittle. The
  prompt already says "Output only that"; the model complies most of the time and the parser should
  not punish the remainder for being correct.
- **Raise `MAX_ANSWER_TOKENS` again** (12 → 16 was ADR 0067). Rejected: it is the wrong axis. The
  samples run to 20+ tokens, the next ones will run longer, and each raise weakens the guard for
  replies that genuinely state nothing.
- **Drop the negation/acting word lists.** Rejected — they still catch "…mentions research, but
  none fit", which answer-last correctly leaves invalid. Keeping both, ordered, is strictly better
  than either alone.
- **Count an unmeasured prompt as a miss instead of failing.** Rejected, again (ADR 0064/0067): a
  fabricated 0.0 is worse than a loud failure. Nothing here changes that.
