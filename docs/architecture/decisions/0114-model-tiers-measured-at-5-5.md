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
claude-haiku-5-5}`. `run_agent_evals` and `run_skill_evals` take their `--model` default from `TIERS["default"]`; the
other CLIs (`run_tier1_evals`, `run_activation_evals`, `run_spine_e2e`, `ralph`, `pr_watch`), the `eval.yml` input
and the config schema's example name `claude-opus-5-5`.

**2. The judge is held still.** `build_runners(..., grader_model=None)` grades on `grader_model` when given, else on the
component's model as before. `run_agent_evals` and `run_skill_evals` take `--grader-model` and pass `--grader-model or
--model`, never the component's tier, and the benchmark records `grader_model`.

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
- **`qa-engineer` → `simple`.** Writing and running tests against a stated change; it scored at least as well on Sonnet.
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
