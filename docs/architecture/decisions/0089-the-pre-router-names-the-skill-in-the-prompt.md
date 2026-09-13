# ADR 0089 — The pre-router names the skill in the prompt

Status: Accepted (implemented)
Date: 2026-09-13

## Context

ADR 0088 measured unprompted skill activation at **0.347** and found its shape: a skill fires in
inverse proportion to how easily the model can just do the task itself. The cheapest intervention —
two sentences in the SessionStart `additionalContext` saying skills are workflows, invoke them
*especially* when doing it by hand looks easy — lifted the pooled rate to **0.560** (2026.9.3).

That leaves nearly half. And the residue is concentrated exactly where the baseline said it would
be: `code-review`, `develop`, `security-review` at 0.200–0.250, the skills with both an obvious
manual path and a built-in namesake. A standing note is advice the model weighs once, at session
start, against everything else in context. The moment that matters is later: a specific prompt has
just arrived, and the model is deciding — in one step — whether to reach for a skill or for `Bash`.
Nothing speaks to it *at that moment*.

Step 3 of ADR 0088's sequence is something that does.

## Decision

A **`UserPromptSubmit` hook** — `plugin/hooks/scripts/pre_router.py`, logic in
`plugin/lib/agentic_forge/pre_router.py` — that classifies each prompt against the plugin's skills
and, only on a clear match, adds one line of `additionalContext` naming that skill and saying to
invoke it. It suggests; it never invokes; it ends *"if the request is really something else, ignore
this"*.

**It is deterministic and cheap.** No model call, a few milliseconds, runs on the 3.9 the hooks are
contracted for (ADR 0050). The classifier is a bag of words over the plugin's own data:

- Each skill's **profile** is its description's features plus its `evals.json` `should_trigger`
  prompts' — word unigrams and bigrams after stop-word removal and a crude stem.
- A prompt is scored by **IDF-weighted coverage**: the share of the prompt's weighted features
  that the profile explains, in [0, 1]. Asymmetric on purpose — a long description is not
  penalised for being long, and a short prompt is scored on how much of *it* the skill accounts
  for.
- **IDF is computed across skill profiles**, one document per skill — so a word is discounted for
  appearing in many *skills*, not many examples. `feature` and `review` are in most profiles and
  weigh little; `changelog`, `incident`, `wcag` are in one and weigh a lot. That is the axis the
  decision is made on.
- A skill is suggested only when it **wins clearly**: coverage ≥ `MIN_SCORE` (0.40), at least
  `MARGIN` (0.15) ahead of the runner-up, and not vetoed by its own `should_not_trigger`
  vocabulary covering ≥ `NEG_VETO` (0.50) of the prompt. Anything less abstains. Precision over
  recall, because a wrong nudge on every prompt is the failure mode, and a hook that fires on
  everything is ignored on everything.

**Calibration is a test, not a hope.** `self_check()` runs leave-one-out over all 84 trigger and
71 anti-trigger prompts — each classified with itself removed from the index — and
`test_self_check_precision_holds` pins the contract: recall ≥ 0.5, precision ≥ 0.9, wrong-skill ≤
2, false-suggest ≤ 2. At the chosen thresholds: **recall 0.500, precision 0.955, wrong-skill 0,
false-suggest 2**.

## What the self-check caught before it shipped

The first cut scored recall **0.024**. Two design flaws, both invisible without the check:

1. **The contrastive-clause leak.** This plugin's descriptions are deliberately contrastive — *"Not
   for the technical design (architecture)"*, *"For a quick lint of a single-file diff use
   code-review instead"*. That is exactly what makes the *model* route well (Tier-1 at 1.000), and
   exactly what poisons a bag of words: it put `prd` into `architecture`'s profile, `implement`
   into `security-review`'s, and `thorough adversarial review` into `code-review`'s, which then
   won the very prompt written for `deep-review`. Fixed by subtraction: a skill's description loses
   any word that belongs to another skill's trigger prompts and not to its own. Words the skill's
   own triggers use are kept whatever the neighbours say.

2. **Unknown words weighed nothing.** A feature no profile contained had IDF 0 and vanished from
   the denominator, so *"Run the app and screenshot it"* — `run` and `screenshot` unknown — scored
   0.60 for `deep-review` on the single word `app`. A word none of the skills use is the strongest
   evidence a prompt is about something else; unknown words now carry the maximum weight.

The three false suggestions that remain share one shape — an anti-trigger that names the *same
fixture feature* as the skill's triggers (*"Implement the saved-searches feature"* against
`ux-design`, whose triggers also mention saved-searches). The verb is the discriminator and it is
foreign; the noun wins on coverage. In production these exact prompts sit in the index and the
negative veto catches them; leave-one-out removes them by construction, so the reported precision
is a floor.

## Consequences

- Every prompt now carries, when the match is clear, the one line the SessionStart note could not:
  *this* request is *that* skill. The measurement that decides whether it helps is Tier-1b against
  the 0.560 bar — run, not assumed.
- `pre_router.enabled` (default **off** — see *Measured* below) and `AGENTIC_FORGE_PRE_ROUTER=1`
  opt in. It fails open and records its own crash (ADR 0039).
- The classifier's quality is now a Tier-0 property: editing a description or a trigger prompt
  that breaks the leave-one-out contract fails `pytest`. That is a new, cheap, deterministic guard
  on exactly the data the router runs on.
- The contrastive-clause subtraction is a statement about this plugin's description style, not a
  general NLP claim. A plugin whose descriptions do not name their neighbours would not need it and
  would not be harmed by it.

## Measured — and shipped off by default

Same 84 prompts, same model, on top of the session note (ADR 0088):

```
pooled           note 47/84 = 0.560  ->  +pre-router 55/84 = 0.655   (+0.095, +8 prompts, z = 1.27)
the middle band  marketing 3->8/9   release 2->4/4   qa-test-strategy 3->4/4   ux-design 2->3/4
                 architecture 3->4/5   product 3->4/5   knowledge 4->5/5
the hard four    code-review 1->1/5   develop 1->1/5   security-review 1->0/4   deep-review 3->2/5
```

Three readings, in order of weight:

1. **Not proven.** z = 1.27 is inside single-run noise; the pre-stated criterion was "inside noise
   means not proven", and it applies. Against the 0.333 baseline the cumulative chain reads +0.321
   (z = 4.40), but that is almost entirely the note's.
2. **An upper bound, not an estimate.** There was no control group to lean on: with the full index
   the hook fires on all 84 eval prompts, because they are its own training data. On real prompts it
   fires at roughly its leave-one-out recall, 0.50. The eval inherited the classifier's data, and a
   held-out prompt set is the debt that leaves.
3. **Zero effect where it was aimed** — and this is the finding. *(Retracted 2026-09-13, ADR
   0090: on that stand the four skills had nothing to run on — an empty directory — so the null
   result is uninterpretable, not negative. The reading below did not survive the diagnostic
   that was scheduled precisely to test it.)* The four skills with an obvious
   by-hand path received the *exact skill name* in the prompt's own context and did the work by
   hand anyway. For them the bottleneck is not routing information; the model knows and declines.
   The description-as-price-list hypothesis (ADR 0088's step 4) is now the one worth testing.

So the hook does not ship on. `pre_router.enabled` defaults to **false**; `AGENTIC_FORGE_PRE_ROUTER=1`
opts in, for a user who wants the middle-band lift and accepts it is unproven. The code stays, and
so does its leave-one-out contract in `pytest` — a cheap, deterministic guard on the trigger data
the router runs on — and it keeps a job if the Stop-hook contract (step 2 of the roadmap) is built:
a hook that blocks a session must not do so without a confident classifier behind it.

## Alternatives considered

- **A model call in the hook** (ask a small model "which skill?"). Rejected: a model call on every
  prompt is latency and cost on every prompt, and Tier-1 already shows the model routes at 1.000
  when asked — the problem was never the answer, it was that nobody asked. A lexical hint that
  makes the model ask itself is enough, and it is free.
- **Have the hook invoke the skill** (rewrite the prompt into `/agentic-forge:x …`). Rejected: a
  hook that overrides what the user asked is the ADR 0073 failure with a different face. The line
  is a suggestion the model can decline, and says so.
- **Symmetric cosine similarity** over examples (the first cut). Rejected by its own number, 0.024:
  short trigger prompts share boilerplate across skills, and a long description scores low against
  any short prompt. Coverage of the prompt by the profile is the question actually being asked.
- **Match on descriptions alone**, skipping the trigger prompts. Rejected: the triggers are what
  the plugin already declares as "this is what the skill is for", and they anchor the profile where
  the description is abstract. Skipping them would also lose the self-check's data.
- **Tune thresholds for recall** (0.30 / 0.05 gives 0.690 recall at 0.879 precision, 3 wrong).
  Rejected: three prompts routed to the wrong skill, on every prompt that resembles them, is a
  worse product than a hook that stays quiet half the time. The band 0.30–0.50 never routes wrong
  above MARGIN 0.10; the chosen point buys the last of precision with the last of recall.
