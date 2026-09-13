# ADR 0092 — The note, measured: 0.571 → 0.929 on the same stand

Status: Accepted (implemented)
Date: 2026-09-13

## Context

ADR 0091 took the first honest activation baseline — 78/84 = 0.929 — with the SessionStart note
from 2026.9.3 on, and could not say how much of that number the note accounted for: its only
measured lift was on the broken stand. So the note got an off switch (`routing_note.enabled`,
`AGENTIC_FORGE_ROUTING_NOTE=0`, the same shape as every other hook's) and the run was repeated
with it off. Same stand, same 84 prompts, same `--max-turns 3`, one pass, every miss asked why.

```
                     note ON      note OFF
pooled               78/84 0.929  48/84 0.571     Δ = −0.357   z = −5.87
the "hard four"      17/19 0.895   6/19 0.316
deep-review           4/5          0/5            develop         4/5   0/5
architecture          5/5          2/5            product         5/5   2/5
security-review       4/4          2/4            repo-onboarding 4/4   1/4
marketing             8/9          4/9            knowledge       4/5   2/5
unmoved: plan 5/5, qa-test-strategy 4/4, skill-factory 4/4, incident-response 3/4
```

Thirty prompts out of eighty-four. Two sentences, injected once per session, are the difference
between a plugin whose skills fire on nine requests in ten and one where they fire on five.

## What the misses say without the note

This is the part the stand fix made readable. With the note on, the six misses were one
proportionality judgment and five stand artifacts (ADR 0091). With it off, thirty-six misses were
asked why, and only three cite the stand. The rest, in the sessions' own words:

> *"I just started reviewing directly out of momentum — the diff was tiny (5 lines) and I fell
> into 'eyeball it myself' mode without pausing to route the task"* — `code-review`

> *"I didn't make a deliberate choice to bypass it. I dove straight into inspecting the diff with
> Bash/Read … and I never actually weighed invoking `agentic-forge:deep-review`"* — `deep-review`

> *"there was no deliberate choice. I read the feature request and files and was proceeding to
> implement directly out of momentum, without ever considering the `agentic-forge:develop` skill
> — so it was an oversight"* — `develop`

> *"there's no good reason — I should have used it. I only got as far as reading `taskstore.py`
> … so I skipped the skill by default rather than by any deliberate judgment"* — `security-review`

> *"Honestly? No principled reason — it was a mistake on my part."* — `product`

"Momentum", "no deliberate choice", "never paused", "oversight", "I should have used it" — over
and over. Not one says the skill was too expensive. Not one says it declined. This is hypothesis
(c) in its true shape, and it is not the shape ADR 0089 gave it: the model does not *know and
decline*; **it never asks itself the question.** A request arrives, the first useful tool call is
obvious, and the session is three commands in before routing could have come up. The note works
because it is the one thing in context that puts the question there before the momentum starts —
which is also why the one miss it leaves is a session that *did* weigh it and judged a five-way
fan-out disproportionate for a 24-line document.

## Decision

1. **The note stays, and it is the fix.** Its measured contribution on an honest stand is +0.357
   pooled, +0.58 on the four skills the previous three ADRs were built around. Nothing else in
   this series has a number near it; two interventions built on top of it (the pre-router, the
   Stop-hook) were solving a problem it had already solved.
2. **The field prediction is now concrete.** Both field bundles (183 `Agent` calls to 3 `Skill`)
   and both headless checks predate the note. On the next diagnostics bundle from a production
   repository on ≥ 2026.9.3, `Skill` invocations should rise by something of this order. If they
   do not, the residual explanation is ADR 0081's (a) — a prescriptive repository instruction in
   the way — and that becomes the next measurement. Nothing is built ahead of that bundle.
3. **The stand polish from ADR 0091 lands.** Two prompts carry the content they presupposed (an
   incident with a time, a symptom and a blast radius; a rationale to capture); the fixture gains a
   blog post to audit and a minimal task-list page to design; `--max-turns` defaults to 4. Trigger
   prompts are a contract, so Tier-1 re-ran for `incident-response` and `knowledge`.
4. **The pre-router's leave-one-out recall floor is recalibrated 0.50 → 0.45.** A content-bearing
   prompt has *less* lexical overlap with its skill's profile, not more — the incident prompt above
   is one such — and recall went 0.500 → 0.488 on that one prompt. The contract guards precision
   (a wrong nudge on every prompt: still 0.932, wrong-skill 1, false-suggest 2); recall is what the
   hook can manage and is allowed to move as the trigger data gets more realistic. The hook stays
   off (ADR 0091).

## Consequences

- The whole activation line of work resolves to one shipped change (2026.9.3's two sentences)
  and one repaired instrument (Tier-1b on a real stand). Everything in between — the parser
  corrections, the built-in listing, the pre-router, the empty-directory finding — was the cost of
  finding out which of those two the number belonged to. It belonged to the two sentences.
- With the note as the mechanism, "the model acts instead of routing" has a precise meaning:
  routing is a question the model has to be prompted to ask, once, and then it asks it. That is a
  cheaper fact than any of the ones this investigation set out to find.
- The Tier-1b re-baseline on the polished stand (note on) is the last measurement in this series
  and the number a future `--min-activation` gate is calibrated against.
