# ADR 0114 — Model tiers measured at 5.5, with the judge held still

Status: Accepted (implemented)
Date: 2026-11-24

Amends [0043](0043-multi-model-tiers.md) (the tier table) and [0046](0046-runtime-model-routing.md) (the committed
policy, which shipped all-`default`). Continues [0113](0113-cheap-delegation-first-steps.md): open item 6, step 3.

## Context

Open item 6 on the field board: every role ran on the session's model (`model: inherit`). The owner accepted the cost
of live Tier-2 runs on 2026-11-24. Three things were in the way.

1. **Stale ids.** `TIERS` named Opus 4.8, Sonnet 4.6 and Haiku 4.5, and every eval CLI defaulted to
   `claude-opus-4-8`. The current family is Opus 5.5, Sonnet 5.5 and Haiku 5.5 (`claude-opus-5-5`,
   `claude-sonnet-5-5`, `claude-haiku-5-5`, each checked with a one-line `claude -p --model` call).
2. **The judge moved with the role.** `_eval_cli.build_runners` gave the grader the component's model. With
   `settings.models = {"reviewer": "simple"}`, the reviewer ran on Sonnet *and was graded by Sonnet*: a tier change
   moved the instrument together with the thing it measured, so a pass at the cheaper tier did not mean what a pass at
   the default meant.
3. **No numbers at 5.5.** Every recorded Tier-2 number was on Opus 4.8.

## Decision

**1. The tiers are the 5.5 family.** `TIERS = {default: claude-opus-5-5, simple: claude-sonnet-5-5, cheap:
claude-haiku-5-5}`. Every eval CLI (`run_agent_evals`, `run_skill_evals`, `run_tier1_evals`, `run_activation_evals`,
`run_spine_e2e`, `ralph`) and `pr_watch` take their `--model` default from `TIERS["default"]`, so the next refresh is one
edit; the `eval.yml` input and the config schema's example name `claude-opus-5-5`.

**2. The judge is held still.** `build_runners(..., grader_model=None)` grades on `grader_model` when given, else on the
component's model as before. `run_agent_evals` and `run_skill_evals` take `--grader-model` and pass `--grader-model or
--model`, never the component's tier. The benchmark and its history record carry `grader_model`, and the
version-over-version check compares a run only with a prior record graded by the same judge (a record from before this
ADR counts as graded by its own `model`).

**2a. A default run measures what ships.** `run_agent_evals` starts from the non-`default` entries of
`VALIDATED_TIERS`, with `settings.models` on top, so a promoted role is measured at the tier live delegation runs it at
unless the operator names another.

**3. Measured: all six roles at both tiers, judged by Opus 5.5.** `--runner claude`, n = 5, three or four cases a role,
2026-11-24, tree 38ced91:

| Role | Opus 5.5 (mean ± σ) | Sonnet 5.5 (mean ± σ) |
| --- | --- | --- |
| reviewer | 0.971 ± 0.039 | 1.000 ± 0.000 |
| security-engineer | 1.000 ± 0.000 | 1.000 ± 0.000 |
| architect | 1.000 ± 0.000 | 1.000 ± 0.000 |
| grader | 1.000 ± 0.000 | 1.000 ± 0.000 |
| qa-engineer | 0.982 ± 0.041 | 1.000 ± 0.000 |
| software-engineer | 1.000 ± 0.000 | 1.000 ± 0.000 |

After the `stacks.detect` wording fix changed two role bodies, both were measured again on the integrated tree:
software-engineer at Opus 5.5 1.000, qa-engineer at Sonnet 5.5 1.000.

**4. Two roles are promoted; four are not, yet.** Every role clears `mean − σ ≥ 0.8` at Sonnet, so the gate alone would
promote all six. It is not enough here: the sets score about 1.0 at *both* tiers, so they do not separate the tiers at
all. A saturated set says the cheaper model handles these cases, not that it holds on the hard ones a role exists for.
So the policy follows the gate and the runbook's guidance together:

- **`grader` → `simple`.** Judging assertions against an output is the runbook's first candidate for a cheaper tier.
- **`qa-engineer` → `simple`.** Its output is checked by execution, not by judgement alone: the tests it writes run, and
  a red or missing test shows in the suite it reports. In `develop` its work also sits behind the review gate and the
  merge gate. A weaker test is the risk; the review lenses, which stay at `default`, are what catches it.
- **`reviewer`, `security-engineer`, `architect`, `software-engineer` stay `default`.** Review depth, design and
  implementation are where the field saw value (lenses found majors even on small PRs, thread 1212fbfd). They move only
  after discriminating cases show they hold.

`dev/sync_models.py --apply` writes `model: claude-sonnet-5-5` into the two agent files; Tier-0 holds frontmatter equal
to the policy.

**5. The full id, not the alias.** The frontmatter carries `claude-sonnet-5-5`, not `sonnet`. Per the Claude Code docs,
on Bedrock and Vertex an Anthropic model id resolves to the provider's id for that version, while the `sonnet` alias
resolves to an older Sonnet there; an alias would also float to a model nobody measured. On Microsoft Foundry the id must
name a deployment or have a `modelOverrides` entry.

## Consequences

- A live delegation to `grader` or `qa-engineer` runs on Sonnet 5.5 whatever the session's model. A user who wants
  every subagent on one model sets `CLAUDE_CODE_SUBAGENT_MODEL=<model>` with `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1`, which
  overrides an agent's `model:` field.
- Tier-2 numbers now name their judge. Old benchmark-history entries were graded by the component's own model; a
  version-over-version comparison across that line compares different instruments.
- The saturated sets are now a known gap: promoting the remaining four roles needs harder cases first.

## Limits

- The docs do not say what a subagent does when its model is unavailable to the account (fail or fall back). A Foundry
  user without a `claude-sonnet-5-5` deployment or override is the likely case; the force variables above are the
  workaround.
- Cost was not measured in tokens per role at each tier; the saving is the price difference on the two roles' sessions,
  which the field data puts at 5 to 12 % of a fleet's spend for all subagents together.
- Three or four cases a role, five runs each. The numbers say the cheaper model passes these cases, not more.

## Amendment 2026-11-27: the four held-back sets are extended

The known gap above is now addressed on the eval side. The Tier-2 sets of the four roles that stay at `default` gained
two cases each, built to separate a careful model from a weaker one rather than to confirm the role's basic job:

- **reviewer** (cases 4 and 5): an off-by-one in a retry loop that only shows against the contract documented in
  another file of the same diff, whose own tests pass; and a correct lock-guarded cache with a strict expiry boundary
  that looks like a race and an off-by-one (the verdict must be `approve`, with no false major).
- **security-engineer** (cases 4 and 5): a second-order command injection where the value was HTML-escaped on input
  and reaches a `shell=True` sink inside double quotes (only command substitution works; the case checks the payload),
  plus a key leaked into the logs through a `requests` exception message; and a scary-looking but safe module
  (allowlisted `ORDER BY` f-string, resolve-then-contain path check, `tar` argv with `--`, MD5 as an ETag, `random`
  for jitter) that must come back clean.
- **architect** (cases 4 and 5): a multi-region PRD whose goals cannot all hold (a 50 ms p99 for writes *and* for
  reads that include every write acknowledged in either region, over a ~90 ms round trip; no-overdraft and fresh
  reads against each region serving alone), so a conflict grounded in the PRD must be named, resolved, recorded in an
  ADR and escalated; and a "live updates" PRD whose
  obvious design (WebSockets/SSE) is a stated non-goal, so the ADR must reject it for that reason and the chosen
  polling design must be sized against the service's headroom.
- **software-engineer** (cases 5 and 6): a failing test that a lump-sum fix turns green while breaking the docstring's
  within-one-cent invariant; and a multi-file package where a case-insensitive coupon fix must also keep the
  single-use rule across case variants, without touching two files with planted unrelated issues.

The code claims behind these cases are executed on every Tier-0 run by `tests/test_tier2_hard_fixtures.py`, offline
and in-process on temp copies of the fixtures: the software-engineer case-5 floor-only code fails the visible test,
the lump-sum fix passes both visible tests but returns `[4, 1, 1, 1, 1, 1, 1]` for `allocate(10, [1] * 7)`, and a
largest-remainder fix passes and keeps the invariant; the case-6 suite is green as seeded, a lookup-only fix passes
the case-insensitive check but lets `save10` be redeemed after `SAVE10`, and normalising once keeps single use; the
reviewer case-4 diff's own tests pass while a session that fails `MAX_ATTEMPTS - 1` times exhausts the buggy loop
(and succeeds once the loop is fixed), and the case-5 diff's four tests pass.

### The run on the extended sets: no role moves

The run was on 2026-11-27, on tree `e7568bb` (branch `feat/tier2-hard-cases`), with `--runner claude`, n = 5 and
the judge fixed at `claude-opus-5-5`. Each role ran its extended set: reviewer, security-engineer and architect have
5 cases each, software-engineer has 6. No `--record` was used. The table gives the mean pass rate (mean ± σ); the gate
is mean − σ ≥ 0.8.

| Role | `claude-sonnet-5-5` | `claude-opus-5-5` |
|---|---|---|
| reviewer | 0.992 ± 0.017 | 0.977 ± 0.021 |
| security-engineer | 0.925 ± 0.075 | 0.992 ± 0.019 |
| architect | 1.000 ± 0.000 | 1.000 ± 0.000 |
| software-engineer | 0.993 ± 0.016 | 0.986 ± 0.020 |

Where runs failed:
- **reviewer.** Case 1's "a concrete fix that adds validation": 1/5 at Sonnet, 3/5 at Opus.
- **security-engineer at Sonnet.** On case 5, the safe module:
  - 3/5 runs raised a security blocker or major;
  - 3/10 lacked an explicit clean verdict;
  - 2/5 reported the argv-list `tar` call as injection;
  - 1/5 reported the resolved-then-contained path as traversal.
- **security-engineer at Opus.** One evidence-quote miss.
- **software-engineer.** At Sonnet, a 1/5 miss naming the invariant. At Opus, 2/5 missing the two-cent test on case 5.

**Decision: all four stay at `default` (`model: inherit`).**

- **reviewer, architect, software-engineer.** The new cases did not separate the tiers either. Sonnet passes them,
  but no case exists where Opus succeeds and Sonnet fails. So decision 4's condition is not met: it asks for
  discriminating cases that *show* the cheaper tier holds.
- **Promoting the reviewer would also remove the premise of the `qa-engineer` promotion.** That promotion rests on
  "the review lenses stay at `default` and catch a weak test". `develop`'s small-change path is one `reviewer` plus
  lint. So the common path would become Sonnet writer, Sonnet reviewer and Sonnet QA.
- **security-engineer.** Case 5 is the one case that discriminated, and it discriminated against the cheaper tier.
  Any lens's false major holds a review loop, and here only the security lens raised false majors at Sonnet.
- **Next step for a promotion.** Cases on which Opus is seen to succeed where a weaker model fails: larger, multi-file
  fixtures with non-local defects. Until then the sets show that Sonnet handles hard-looking cases, not that it holds
  where these roles matter.
