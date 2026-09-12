# ADR 0083 — The weekly eval measures routing, not everything

Status: Accepted (implemented)
Date: 2026-09-12

## Context

ADR 0082 found the weekly `eval.yml` cron reporting success in ~28 seconds with every model-backed
step skipped, and made a scheduled run fail when it cannot measure. That was the right half of the
fix. It left the other half unasked: **what would happen if the token were actually set?**

Sizing the suite the cron would then run:

| step | volume |
|---|---|
| Agent Tier-2 | 6 roles → **95** graded sessions |
| Skill Tier-2 | 21 skills, 2-6 cases x 5 runs → **265** full sessions |
| Skill Tier-1 | 17 skills x 5 runs |
| Tier-3 | the spine scenario plus four domain chains, each multi-phase |

For calibration, measured the same day: `deep-review` alone — 4 cases x 5 runs, 20 sessions — took
the better part of an hour. The Tier-2 half is ~360 sessions of the same kind, and a GitHub-hosted
job is capped at 6 hours (`eval.yml` set no `timeout-minutes`, so it inherited exactly that).

So setting the secret would have converted a silent skip into a weekly red timeout, plus a
substantial recurring draw on a personal subscription — and still no measurement. "Fail when you
cannot measure" is only honest if what you ask to measure is measurable.

## Decision

Split `eval.yml` into three jobs sized to how often the thing they check actually changes.

1. **`wiring`** — every triggering event, no credentials, ~1 minute. Contracts, role prompts and
   fixtures resolve. Runs on forks; catches a mis-wired component for free.
2. **`trigger`** — Tier-1 routing, on the **weekly cron** plus dispatch and the `eval` label. This
   is the regression the schedule exists for: the router listing sits at its context ceiling
   (principle 2), so an edit to one description can break a neighbour's routing, and nothing else
   in the pyramid catches that. ADR 0082's fail-when-blind guard moves here.
3. **`quality`** — Tier-2 (agents + skills) and Tier-3 E2E, **on demand only**: `workflow_dispatch`
   or the `eval` label. These tiers move with a release or with a change to a role, not with the
   calendar.

Every job declares `timeout-minutes` (15 / 120 / 350) so a hung run cannot silently consume a
6-hour runner, and each writes to its own job summary which tiers it measured. `workflow_dispatch`
gains a `tiers` input (`all` / `trigger-only`) so a manual run can stay cheap on purpose.

## Consequences

- The weekly bill drops by roughly an order of magnitude, and what remains is the check whose
  failure mode this project has actually observed in the field twice.
- Tier-2/Tier-3 regressions can now reach `master` without CI noticing. That is a deliberate trade:
  they are release-gated by the definition of done in the roadmap, and the cost of catching them
  weekly is not payable. The release checklist is the backstop, not the cron.
- A PR labelled `eval` still runs everything, which is the pre-release path.
- `CLAUDE.md` and the eval runbook now say which tiers are weekly and which are on demand, so the
  claim in the constitution matches the workflow file. That mismatch is what ADR 0082 was about.

## Alternatives considered

- **Keep the full pyramid weekly and raise the timeout.** Not possible on GitHub-hosted runners
  (6 hours is the ceiling, not a default), and self-hosting a runner to make a weekly full eval fit
  is a large operational change to buy a check nobody was asking for.
- **Shard Tier-2 across parallel jobs.** It would fit the clock, not the budget: the same ~360
  sessions still run, weekly. The cost is the model time, not the wall time.
- **Lower `runs` from 5 to make it fit.** Rejected — the Tier-2 gate is `mean - stddev`, and fewer
  runs widens the interval exactly where the threshold is decided. A cheaper number would be a
  worse number, not a smaller one.
- **Drop the schedule entirely and rely on the `eval` label.** Rejected: routing regressions do not
  arrive with a PR that anyone thinks to label — the field evidence is that they sat unnoticed for
  two months. A weekly Tier-1 is the cheapest thing that would have caught them.
