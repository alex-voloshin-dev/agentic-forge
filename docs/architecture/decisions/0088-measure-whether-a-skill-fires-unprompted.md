# ADR 0088 — Measure whether a skill fires unprompted

Status: Accepted (implemented)
Date: 2026-09-12

## Context

Four ADRs of instrumentation (0082–0087) drove the Tier-1 routing eval to a clean state: with the
answer-last and answer-first parser rules and the built-in-listing correction, seventeen of
seventeen skills route at recall 1.000. Yet the field bundles say the opposite happens in practice —
183 `Agent` calls against 3 `Skill` calls over 27 days (ADR 0081) — and a controlled check confirmed
it: two headless `claude -p` sessions on this very repo, plugin loaded, `Skill` tool available,
asked *"review the last commit's code changes"* and *"run a security review of plugin/hooks"*. Both
did the work with `Bash`/`Read`. Neither called a skill. Neither so much as mentioned one in prose.

The pyramid could not see this. **Tier-1 asks "which skill fits?"** and grades the answer — a
question that puts the model in a routing frame it never enters on its own. **Tier-3 runs skills the
harness itself invokes.** The gap between them is the property that actually matters: does a live
session, given a plain request, *reach for* the skill whose whole job is that workflow — or just do
the task by hand? "Routes correctly when asked" and "fires unasked" are different things, and only
the second is how a skill is used.

That gap is also the correct home for the two hypotheses this investigation raised. ADR 0086's (b) —
the built-in listing wins by meaning — was not supported by the data (ADR 0087: not one loss to a
real built-in). ADR 0081's (a) — a competing repository instruction pre-empts the router — cannot be
the whole story either, because these headless sessions had no such instruction and still did not
fire. What is left is (c): unprompted, the model acts instead of routing.

## Decision

Add **Tier-1b: activation** — `plugin/lib/agentic_forge/activation.py` and
`dev/run_activation_evals.py`. Each skill's `should_trigger` prompts run through a real Claude Code
session with the plugin loaded (`claude -p … --plugin-dir <plugin>`, tools `Skill,Bash,Read,…` so
the model *can* do the work); the transcript is scanned for a `Skill` tool call naming that skill.
The metric is the **activation rate** — the fraction of prompts on which the model reached for the
skill unprompted. Pure parsing (`skill_invoked`, `activation_rate`, `run_activation`), stub-tested;
the subprocess is a seam like every other tier.

It is a **measurement, not a gate.** There is no defensible threshold before a baseline exists
(principle 4: thresholds are starting points, set per component with a rationale), so the runner
reports rates and only gates when a `--min-activation` is passed. The first run's job is to produce
the number, not to pass or fail.

A skill *named in prose* does not count — only an actual tool call — because acting-vs-routing is
the whole distinction being measured. A skill loaded namespaced (`agentic-forge:code-review`) or
bare both count for that skill.

## Consequences

- The property the field reports are about is now measurable in CI, on demand, without waiting for
  another bundle. It is the eval the previous six ADRs kept circling: they perfected the answer to a
  question the model does not ask itself.
- The intended sequence, recorded in the roadmap: (1) take the baseline; (2) the cheapest
  intervention — one line in the SessionStart `additionalContext` that already carries the vault map,
  telling the model to invoke a matching agentic-forge skill rather than do the work by hand — then
  re-measure the lift; (3) only if that is not enough, a deterministic `UserPromptSubmit` pre-router
  hook that names the matching skill in-context from the same `evals.json` trigger prompts; (4) only
  then, description edits under the listing budget. Each step is measured before the next.
- Tier-1b is **not** wired into the weekly cron. Like Tier-2/Tier-3 it is model-time-expensive
  (~85 full sessions) and belongs on demand (ADR 0083); it will earn a schedule if it earns a
  threshold.

## The parser correction shipped alongside

The Tier-1 run that motivated this also produced one more off-format loss: `skill-factory`'s
`none The user is asking a general conceptual question…` — the answer stated **first**, the
explanation after, rejected 4/5 for length. ADR 0085 handled answer-*last*; this is its mirror.
`_leading_choice` now accepts a reply that opens with a known name or `none` when what follows
starts a new sentence (a boundary or a capital). A leading word that is merely the first word of a
sentence (`research is not the right skill…`) still does not qualify — same discipline as
answer-last, same tests both ways.

## The baseline

Run 2026-09-13, `--runner claude --model claude-opus-4-8`, one pass per should_trigger prompt
(85 sessions). Ungated — this is the number, not a verdict.

```
0.000  code-review, deep-review, develop, security-review
0.200  architecture, knowledge
0.222  marketing        0.250  release, repo-onboarding
0.400  plan, product, research
0.500  ux-design        0.571  deploy-watch
0.750  incident-response, qa-test-strategy
1.000  skill-factory
mean activation: 0.347
```

The number confirms the problem: on average the model reaches for the right skill on barely a
third of the requests that are squarely in its domain — and does the work by hand on the rest,
exactly as the field bundles and the headless check showed.

The **shape** is the finding, though, and it is not the "doers vs. document-writers" split
predicted. The zeros are the skills with an obvious do-it-directly path or a Claude Code built-in
of the same shape: `code-review` / `security-review` (built-in namesakes), `develop` / `deep-review`
("just write / just review the code"). The top is `skill-factory` at 1.000 — building a plugin
component has *no* by-hand path, so the skill is the only way through. Reading across the column:
**a skill fires in inverse proportion to how easily the model can just do the task itself.** That
sharpens hypothesis (c) into something actionable — the intervention has to make invoking the skill
the obvious move precisely where doing it by hand is also obvious.

One caveat on precision: single-pass rates are noisy (`deploy-watch` was 0.714 on a 2-skill smoke
minutes earlier, 0.571 here). The mean and the coarse bands are the signal; a one-notch difference
between two adjacent skills is not. A calibrated threshold, if one is ever set, needs multiple runs
per prompt like the other tiers.

## The intervention, and its lift

Step (2) of the sequence, run the same day against the same 84 prompts, same model, one variable
changed: `SKILL_ROUTING_NOTE` in the SessionStart `additionalContext` — two sentences saying that
agentic-forge skills are workflows with gates and handoff artifacts that doing the task by hand
skips, and to invoke the matching skill *especially when doing it directly looks straightforward*.
The wording targets the baseline's **shape**, not its mean.

```
pooled          28/84 = 0.333  ->  47/84 = 0.560      (+0.226, +68% relative, z = 3.03)
mean of rates   0.347          ->  0.561
the four zeros  code-review 0.000->0.200   deep-review 0.000->0.600
                develop     0.000->0.200   security-review 0.000->0.250
biggest movers  plan 0.400->1.000   deploy-watch 0.571->1.000   knowledge 0.200->0.800
unmoved         skill-factory 1.000 (nothing to gain), incident-response / qa-test-strategy 0.750,
                ux-design 0.500, repo-onboarding 0.250
only regression research 0.400->0.200 (one prompt — inside single-run noise)
```

**Every one of the four zeros moved off zero**, which is the prediction the baseline's shape made:
the skills that lost to "I could just do this" are exactly the ones an explicit instruction
recovers. Nothing that already worked regressed — `skill-factory` held at 1.000.

The pooled lift is outside single-run noise (z = 3.03 on 84 paired prompts, 19 net prompts flipped
to activation), unlike any individual skill's row, where ±0.2 is one prompt. That is why the
decision rests on the pooled number and the zeros, and why `research`'s −0.200 is not read as harm.

So the intervention ships. It does **not** finish the job: 0.560 means the model still does the
work by hand on nearly half the requests squarely in a skill's domain, and `code-review`,
`develop`, `security-review` remain at 0.200–0.250 — the shapes with both a built-in namesake and
an obvious by-hand path. Step (3), the `UserPromptSubmit` pre-router that names the matching skill
in the prompt itself, still has a job to do, and now has a measured bar to beat: 0.560.

## Alternatives considered

- **Fold activation into Tier-3.** Rejected: Tier-3 drives a skill through its phases to check the
  *artifacts*; it presupposes the skill was entered. Activation is precisely the step before that,
  and mixing them would hide a zero activation rate behind a green artifact check.
- **Gate Tier-1b now at some round number.** Rejected: a threshold before a baseline is the
  fabricated-number failure this project keeps naming. Measure first.
- **Infer activation from the audit log instead of a fresh eval.** Rejected as the primary method:
  the audit log is real signal (and is where the 183-vs-3 count came from), but it is not
  controlled — it cannot isolate a prompt, hold the listing fixed, or A/B an intervention. The eval
  can; the log stays the field cross-check.
