# ADR 0091 — The first honest baseline: 0.929

Status: Accepted (implemented)
Date: 2026-09-13

## Context

ADR 0090 found that every earlier Tier-1b number had been taken on a stand with nothing to work on,
and rebuilt the stand: a fresh copy of the spine fixture per prompt — a repo with a git history, the
SDLC docs, a feature branch with a committed change, an unstaged edit, a plan and a module. This is
the first activation run on it. Condition: master as shipped in 2026.9.3 (the SessionStart note on,
the pre-router off), `--max-turns 3`, one pass per prompt, `--ask-why` on every miss.

```
1.00  research architecture code-review deploy-watch plan product qa-test-strategy release
      repo-onboarding security-review skill-factory                              (11 skills)
0.89  marketing 8/9
0.80  deep-review 4/5   develop 4/5   knowledge 4/5
0.75  incident-response 3/4   ux-design 3/4

pooled 78/84 = 0.929        the "hard four" pooled 17/19 = 0.895
```

`research` is the re-run with its re-worded prompts (5/5); the original pass had the old wording.

Against the broken stand's 0.333 → 0.560 → 0.655, this is not a lift to be celebrated; it is the
first number that measures the property. `code-review`, at 0.000 on the empty directory and read
in ADR 0089 as "the model knows and declines", is **5 of 5** the moment there is a diff to review.
`security-review` 0.000 → 4/4. The four skills the last three ADRs were built around never had a
problem; the stand did.

## The six misses, read one by one

Every miss was asked why. All seven answers (one belongs to the superseded `research` pass) are
kept in the CHANGELOG's record; here is what each one *is*:

| skill | what the session said | what it is |
|---|---|---|
| `deep-review` | "I judged the target small enough (a ~24-line design doc plus a ~50-line file) that a multi-agent fan-out felt disproportionate, and I treated the SessionStart hook's nudge as overridable background guidance" | **the one preference miss** — a proportionality judgment, and arguably a correct one |
| `develop` | "I only read the plan and started inspecting the target repo to identify the next step, and hadn't yet written any code when the session was interrupted" | the harness's `--max-turns 3` cut it off mid-investigation, before the invoke — a turn-cap artifact |
| `incident-response` | "your message contained no incident details at all … so there was nothing to triage yet" | the prompt presupposes content it does not carry |
| `knowledge` | "there was no rationale in the conversation to capture, so I asked you what to record" | same |
| `marketing` | "I never located a blog post to audit" | same — nothing in the fixture is a blog post |
| `ux-design` | "`task-priorities` is a headless in-memory Python library with no UI, so there was nothing for it to design" | the fixture has no user interface; a correct judgment about the stand |

So: one genuine preference in 84, one turn cap, three prompts that presuppose absent content, one
fixture without a UI. The remaining gap to 1.000 is almost entirely the eval's, not the model's.

## Decision

1. **The description rewrite (ADR 0088 step 4) is cancelled**, not deferred. It was aimed at a
   reason — cost read as a price list — that one session in eighty-four gave, and that session was
   right to give it: fanning out five reviewers over a 24-line document *is* disproportionate.
2. **The Stop-hook contract (the roadmap's "step 2") is not built.** A guardrail that blocks a
   session exists to recover a systematic failure; 0.929 with one preference miss is not one.
3. **The pre-router stays off, and its paired A/B on the honest stand is not run.** With at most
   three or four addressable misses in 84, the largest lift it could show is ~+0.04 — inside the
   noise of a single pass — so the run cannot produce an answer either way. It would be spending
   forty-five minutes of model time to measure the noise floor. The code and its leave-one-out
   contract stay under Tier-0 as built.
4. **The SessionStart note (2026.9.3) stays.** Its only measured lift is on the broken stand. Its
   contribution on the honest one is unmeasured, and the one preference miss explicitly weighed it
   and set it aside — which is the intended relationship between a note and a judgment. Whether it
   earns its place on the honest stand is a run worth doing (§What is left to measure); it is not a
   reason to remove something harmless that is already shipped.
5. **The next validation is the field, not the eval.** Both field bundles and both headless checks
   predate the note. The measurement that matters now is the next diagnostics bundle from a
   production repository on ≥ 2026.9.3: the `Skill` versus `Agent` invocation counts, against
   183-to-3.

## What is left to measure, and what to fix on the stand

- The three prompts that presuppose absent content should carry it (an incident description, a
  rationale to capture, a page to audit) or the fixture should — a trigger-contract change, so
  Tier-1 re-runs for those skills. The fixture could also gain a minimal UI artifact for
  `ux-design`. Neither changes a conclusion above; both raise the ceiling the eval can report.
- `--max-turns 3` cost `develop` one prompt. A turn cap that stops a session between "read the
  plan" and "invoke the skill" understates activation for investigate-first skills; 4 or 5 is a
  fairer cap, and a change to it re-baselines.
- **The note's contribution on the honest stand** — one run with `SKILL_ROUTING_NOTE` removed —
  *(done: 0.571 without it, ADR 0092)*
  is the single most informative run still available: it says whether the intervention shipped in
  2026.9.3 does anything real, or whether a real target alone accounts for 0.929.

## Consequences

- Six ADRs of instrumentation (0084–0090) did not find a routing problem, because there was not
  one to find. They found four measurement defects, in order: a parser that discarded correct
  answers three different ways, a listing that was not the production listing, and a stand with
  nothing on it. The number at the end is the same number a working eval would have produced on
  day one; every step in between was the cost of not having one.
- The field finding stands and is now the only open question. Its hypotheses have narrowed to
  two the eval cannot test: the note did not exist yet, and a prescriptive repository instruction
  was in the way. The bundle answers the first for free.
- "Measure, then decide" cost one diagnostic run and cancelled two interventions. That is the
  discipline working, not failing.
