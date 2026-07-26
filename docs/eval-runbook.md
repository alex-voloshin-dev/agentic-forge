# Eval runbook — running the eval pyramid

> **A Tier-1 dip is a measurement question before it is a routing question.** Two distinct failure
> modes look identical from the summary line — both depress `recall` while leaving `specificity` at
> a perfect `1.000`, because a broken call names neither the skill under test nor its neighbours:
>
> 1. **Throttling / failed calls.** Under heavy subscription usage a skill can "fail" recall with an
>    eerily stable number across re-runs (observed 2026-07-14: `product` at exactly 0.840 four
>    times, then 1.000 when calm, with byte-identical inputs). Re-run when calm.
> 2. **Off-format replies** — the model answering in prose instead of with one skill name. Since
>    ADR 0064 these are counted as `INVALID`, dropped from the denominator, and **reported on the
>    summary line** (`[N/M calls returned no decision]`); a prompt where *every* call was invalid is
>    `unmeasured` and **fails** rather than reporting a fabricated `0.0`. Before that fix they were
>    mined for the first skill-like word and scored as a wrong routing decision.
>
> So: read the discarded-call count first. **A non-zero count is normal** — the baseline run under
> the corrected harness (2026-07-25, six skills, runs = 5) discarded **~20 of ~300 calls (6.7%)** and
> still scored a clean 1.000/1.000 across the board. Treat roughly that rate as the channel's noise
> floor; a materially higher one means the run is thin evidence, so re-run before concluding.
>
> **Never edit a description to chase a Tier-1 number until a run reproduces the dip with the
> discards accounted for.** Observed 2026-07-25: `product` scored 0.800 / 1.000 / 0.720 within one
> hour against a byte-identical listing — the "calm" re-run being the worst of the three — and the
> corrected harness then measured it at **1.000**. The cause was neither throttling nor routing, and
> editing the description would have spent the router's ~1% listing budget on a defect that was never
> there. To see *why* a call missed, capture the raw reply — `parse_selection`'s verdict alone cannot
> tell an empty reply from an essay.

> **Growing a description can dilute its existing anchors.** Adding new capability keywords to a
> listing description shifts the router's attention: after `marketing` gained offer/audit
> keywords, its OLD "market research and analysis" prompts started routing to neighbours until
> the original anchor phrasing was restored and the marketing↔product boundary was stated on BOTH
> descriptions. When you extend a description, re-run Tier-1 for the skill AND its nearest
> neighbours, and expect to re-balance the old anchors, not just append the new words.

This explains how to run the project's evals and read the results. It starts with the Tier-2
(LLM-judged quality) evals for the six engine roles (`reviewer`, `grader`, `software-engineer`,
`architect`, `security-engineer`, `qa-engineer`); the other tiers each have their own runner
(see *Scope: a runner per tier* below). The orchestration for the roles is
`plugin/lib/agentic_forge/agent_eval.py`; the CLI is `dev/run_agent_evals.py`; the wiring in
CI is `.github/workflows/eval.yml`. Rationale: [ADR 0011](architecture/decisions/0011-agent-eval-runner.md).

## What it does

For each role, for `runs` independent runs (default 5, from the contract):

1. Run the role on each eval case (the role's system prompt from `plugin/agents/<role>.md`
   plus the case prompt and its fixture files from `plugin/eval/fixtures/<role>/`).
2. Grade the output with the `grader` role against the case's assertions → a `grading.json`
   shape (`text`/`passed`/`evidence` + `summary`).
3. Aggregate the per-run pass rates with `agentic_forge.benchmark.summarize`.
4. Gate with `agentic_forge.gate.tier2_quality`: it passes only if the pass-rate **lower
   bound** (`mean − stddev`) over `runs` ≥ `min_pass_rate` (0.8) and `n ≥ runs` (5).

Why agents have a dedicated runner (not skill-creator): skill-creator evaluates *skills*
(with/without-skill deltas and activation/triggering), none of which applies to delegated
roles. The runner reuses the same policy layer (`benchmark` + `gate`), so the gate is
identical to skills'.

### Scope: a runner per tier

`run_agent_evals.py` gates the six **roles** (agent Tier-2). The other tiers have their own
runners: **Tier-0** `dev/validate.py`; **skill Tier-1** `dev/run_tier1_evals.py` (trigger
recall/specificity on the live listing — see below); **skill Tier-2** `dev/run_skill_evals.py`
(see below); **Tier-3** `dev/run_spine_e2e.py`. The spine phase-workflow skills carry no
skill-level Tier-2 — their quality is exercised end-to-end by the Tier-3 spine E2E plus the agent
Tier-2 of the roles they fork. Every skill that declares a `tier2_quality` threshold (19 today:
`deep-review`, `skill-factory`, `knowledge`, `engineering-standards`, the nine `*-patterns` packs,
and the Stage-4–6 own-behavior skills `release`, `deploy-watch`, `incident-response`, `marketing`,
`ux-design`, `repo-onboarding`) **is run by `run_skill_evals.py`** (ADR 0017) — no longer a manual
step. (The fork-orchestrators `qa-test-strategy` / `security-review` carry no skill Tier-2 by design;
their end-to-end quality is the Tier-3 `quality-gate` domain scenario plus the forked role's agent
Tier-2 — see [domain-e2e.md](architecture/domain-e2e.md) / [ADR 0030](architecture/decisions/0030-domain-e2e-scenarios.md).)

### Skill Tier-1 — `dev/run_tier1_evals.py` (live descriptions)

Tier-1 **is** automated, by a sibling CLI. `run_tier1_evals.py` builds the **live** always-on
listing (every model-invocable skill's `name` + `description`; off-listing `*-patterns` /
`engineering-standards` excluded) and, for each on-listing router skill that declares
`tier1_trigger`, asks the router — the model classifying against that listing — which skill
auto-loads for each trigger prompt. Grading is **deterministic** and scored as the **mean
per-prompt routing rate** over N samples: recall = the mean rate of selecting the skill on
`should_trigger` prompts, specificity = the mean rate of *not* selecting it on
`should_not_trigger` prompts; gated at ≥ 0.9 via `gate.trigger_metrics` + `gate.tier1_trigger`.
(The mean rate replaces the older per-prompt majority-of-N, which flickered around the 50% cliff
and rubber-stamped barely-majority routing — ADR 0016, metric refined by ADR 0026.)
It reuses the same transports — `--runner dry|claude|api` (the `claude` router call runs with
tools disabled and one turn); `dry` verifies the listing/trigger wiring with no auth.

**When recall fails — the remediation playbook
([ADR 0029](architecture/decisions/0029-tier1-routing-remediation.md)):** diagnose *per-prompt*,
not per-skill — route each `should_trigger` prompt K times against the live listing and record
where it actually went; one "killer" prompt usually dominates the failure (leaking to a specific
competitor or to `none`). Fix it by **sharpening the description**: own the leaking prompt's
keywords, add a reciprocal disclaimer on the competitor it leaks to (only where that can't steal
the competitor's own triggers — check them), and remove spurious keyword matches in other skills.
**Never lower the 0.9 threshold.** Reword a `should_trigger` prompt only when it is *genuinely
ambiguous* and fights a router prior no description can beat — and then only to an equivalent that
tests the same capability the skill's other prompts already cover, keeping the prompt count and
threshold unchanged.

### Skill Tier-2 — `dev/run_skill_evals.py`

Tier-2 for skills that declare `tier2_quality` is automated (ADR 0017), reusing the agent
runner's core. Two execution modes:

- **Knowledge skills** (`engineering-standards`, the `*-patterns` packs) have no behaviour of
  their own, so each runs *as the `software-engineer` with it loaded* — system = the
  software-engineer body + `engineering-standards` (+ the pack body) — with the engineer's tools,
  isolated (it writes code), graded against the skill's own assertions. This is the
  "exercised through the software-engineer's Tier-2" path, now real.
- **On-listing skills** (`deep-review`, `skill-factory`, `knowledge`) run directly (own body + tools).

Each output is graded by the `grader` role, aggregated, and gated `mean − stddev ≥ 0.8` over the
contract's `runs`. Same transports (`--runner dry|claude|api`). **It is the most expensive eval**
— a full software-engineer coding session per case × N — so scope local runs with `--skill` /
`--runs`; CI cost-gates it on the subscription token.

#### A/B lift + time overhead — `--baseline` (opt-in, ADR 0036)

Per-run wall-clock timing is always captured (every benchmark reports `with_skill.time_seconds`).
Adding `--baseline` *also* reruns each case under the **without-skill** baseline — the same executor
with the skill under test removed (for a knowledge skill: the software-engineer + standards, minus
the pack; for an on-listing skill: the bare base model) — so the benchmark gains a
`run_summary.delta` with the with/without **pass-rate lift** and the **time overhead**. This roughly
**doubles cost**, so it is off by default:

```bash
python dev/run_skill_evals.py --skill python-patterns --runner claude --baseline
```

A contract opts into gating these via two `tier2_quality` fields, **evaluated only when a baseline
ran** (a normal run ignores them): `min_lift` — the skill's pass-rate must beat no-skill by at least
this much (the "A/B not worse / better by X" bar) — and `max_overhead_seconds` — the added
wall-clock per run must stay within budget. **Calibrate before you gate:** run `--baseline` a few
times, read the reported `delta.pass_rate` / `delta.time_seconds`, then set each bar from the
measurement — never guess a number, and never lower it later to make a run pass (improve the skill
instead). **Token overhead** (`max_overhead_tokens`) is also live: both transports report usage
(the `api` runner from the Messages response; `claude` via `--output-format json`) through a
`RunOutput` reply, so `--baseline` populates `delta.tokens` too (ADR 0038). Calibrate it the same
way.

#### Version-over-version A/B — `--record` + `max_regression` (opt-in, ADR 0047)

With/without measures the value a component adds *now*; version-over-version catches an **edit** that
**regressed** a component below its **prior** version. It compares the current run against a **stored
benchmark history** (the prior run's recorded mean), so it's cheap — no re-run of the old version.

```bash
# 1. record a baseline from a good run (only a healthy run is recorded):
python dev/run_skill_evals.py --skill python-patterns --runner claude --record
# 2. after editing the skill, re-run — it compares against the recorded baseline:
python dev/run_skill_evals.py --skill python-patterns --runner claude
```

A contract opts in with `tier2_quality.max_regression` — the current mean may not drop more than this
below the prior recorded mean, else the run FAILS. The check is **skipped** until a baseline exists
(a first run can't regress) and when no `max_regression` is set. History is keyed by **(component,
model)** — switching tiers (ADR 0043/0046) starts a fresh baseline. The default history file is the
per-repo `.agentic-forge/benchmark-history.json` (gitignored); point `--benchmark-history` at a
committed path to gate version-over-version in CI. A failing or regressed run is **never** recorded,
so the baseline can't be poisoned.

### Authoring assertions: the grader is read-only (ADR 0020)

Grading always runs with **read-only** tools (`Read, Grep, Glob`) — the grader has no `Bash`, so
it can never *run* a build, linter, formatter, test, or `dev/validate.py`. Write every assertion
so the grader can verify it **by reading the work and its files**, not by executing a toolchain:

- ✗ "dotnet build is clean" / "cargo clippy clean" / "eslint clean" / "`dev/validate.py` passes"
  — ungradeable by execution; the grader can only guess, which surfaces as near-0.8 variance.
- ✓ "compiles cleanly on inspection (no missing imports / undefined symbols)" / "clippy-clean
  idioms (no needless clone, no `unwrap()` on the happy path)" / "no new `eslint-disable`" /
  "standard-compliant: valid frontmatter, body ≤ 500 lines, references resolve".

**Exception — a toolchain that is actually present and run by a write role.** The write roles
(`software-engineer`, `qa-engineer`, `architect`) run with `Bash` at Level 2, and the **Python**
toolchain (`pytest`/`ruff`/`mypy`) *is* installed in the sandbox, so they genuinely run it. An
assertion like "the tests are run and reported as passing" is fine **there**: the role executes
the present toolchain and the grader verifies it by **reading the role's run report plus the test
files and the changed code**. The rule targets *absent* toolchains (dotnet/cargo/gradle/node) the
grader can only guess about — not the ones the environment can actually run. When unsure, phrase
for inspection; it never hurts.

When a gate fails, **root-cause per assertion first** (`run_skill_evals.py --skill X --runs 1`,
reading each assertion's grader evidence), then fix at the cause — improve the skill, give the
case a fixture that exercises the assertion, or correct a mis-stated convention — **never lower
the threshold or drop an assertion** (ADR 0020).

## Authentication — use your Claude subscription (recommended)

The `claude` runner shells out to the `claude` CLI, so it uses whatever auth the CLI is
configured with. To bill runs to your **Claude subscription** (no per-token API key):

1. Generate a long-lived subscription token once (requires Pro/Max/Team/Enterprise):
   ```bash
   claude setup-token
   ```
2. Make it available as an environment variable:
   ```bash
   export CLAUDE_CODE_OAUTH_TOKEN=<token from setup-token>
   ```
3. **Ensure `ANTHROPIC_API_KEY` is _not_ set.** It takes precedence over the subscription
   token; if both are present, the run bills per token. (The CLI warns you when it sees both.)

Locally, if you are already signed in to Claude Code (interactive `claude` login) and
`ANTHROPIC_API_KEY` is unset, `--runner claude` uses that session directly — the token above
is mainly for CI/headless runs.

Alternative — per-token billing: set `ANTHROPIC_API_KEY` and use `--runner api` (this path
needs the optional `anthropic` SDK: `pip install -e ".[dev,eval]"`). Most users on a
subscription should use `--runner claude` instead.

## Fidelity levels (the runner seam)

The model/agent invocation is a seam, so there are two production runners:

| `--runner` | How the role runs | Auth | Fidelity |
| --- | --- | --- | --- |
| `claude` (recommended) | headless `claude -p` with the role's tools in a workdir | Claude subscription (or API key) via the CLI | Level 2 — real tool use; write roles (`software-engineer`/`architect`/`qa-engineer`) actually read/write/run |
| `api` | one Anthropic Messages call per task (no tools) | `ANTHROPIC_API_KEY` only | Level 1 — judges the role's *output*; no real file edits or test execution |

With `--runner claude`, grading also goes through the CLI but with **read-only** tools, so the
grader can verify on-disk artifacts (level-2) without ever modifying them; the whole run stays
on your subscription. **Write roles** (anything with `Write`/`Edit` — `software-engineer`,
`architect`, `qa-engineer`) are **always run in a per-case sandbox**: `run_role` forces
isolation for them regardless of `--isolate`, materializing fixtures into a fresh temp workdir
by basename (no repo-relative paths), so a write role can never reach or mutate the real repo.
`--isolate` opts read roles into the same sandboxing. Grading is robust to prose/fenced
grader replies and retries once on an unparseable response.

## Run it

Prerequisites: the `claude` CLI on `PATH` (`npm install -g @anthropic-ai/claude-code`) and
the auth above. Install Python deps: `pip install -e ".[dev]"` (enough for the `dry`/`claude`
runners; `--runner api` additionally needs the `eval` extra: `pip install -e ".[dev,eval]"`).

```bash
# Verify wiring only — no credentials, no model calls (also runs in CI on every eval job):
python dev/run_agent_evals.py --runner dry

# Real Tier-2 on your subscription, all roles (recorded results used Opus 4.8):
export CLAUDE_CODE_OAUTH_TOKEN=...        # and keep ANTHROPIC_API_KEY unset
python dev/run_agent_evals.py --runner claude --model claude-opus-4-8

# Write roles in isolation (fresh temp workdir per case; best for software-engineer/architect):
python dev/run_agent_evals.py --role software-engineer --role architect --runner claude --isolate
```

Exit code is 0 only if every selected role's gate passes. Each role prints a line like
`reviewer: PASS (mean=0.93, stddev=0.05, lower_bound=0.88, n=5)`.

## In CI

`eval.yml` is cost-gated: trigger it via **workflow_dispatch** (optionally choosing a model)
or by adding the **`eval`** label to a PR. Setup:

1. Run `claude setup-token` locally and copy the token.
2. Add it as the GitHub Actions secret **`CLAUDE_CODE_OAUTH_TOKEN`** (repo → Settings →
   Secrets and variables → Actions). Do **not** add `ANTHROPIC_API_KEY`.

The job installs the `claude` CLI (`npm i -g @anthropic-ai/claude-code`), always runs the
dry-run wiring check, and runs the real `--runner claude` Tier-2 when the token secret is
present. A failing gate fails the job. Note: a personal subscription token is a single point
of failure; for team CI prefer a team/enterprise account's token.

## Model tiers (ADR 0043)

`--model` sets the **global default** model. To run a *specific* component on a cheaper tier, set
`models` in `.agentic-forge/config.json` (keyed by role / skill / `router`; value is a tier name —
`default` / `simple` / `cheap` — or a model id):

```json
{ "models": { "grader": "simple", "router": "cheap" } }
```

The runners resolve each component via `models.model_for(...)`, so the **Tier-1 / Tier-2 gate
validates the choice**: a cheaper tier ships only if that component still clears its bar at that
tier (use `--baseline` to weigh the quality/cost trade-off). **Validate before you flip** — never
assume a downgrade is free; re-record the numbers at the new tier. Recommended starting candidates:
routing / grading / recall / simple synthesis → `simple` or `cheap`; implementation / design /
security / adversarial review → `default`. Default (no `models`) = opus everywhere (unchanged).

### Promoting a tier into runtime delegation (ADR 0046)

`settings.models` above is the **eval-time** lever — it validates a candidate tier. To make a
validated tier actually take effect at **runtime** (when a skill forks a role via `Task`), promote it
into the committed policy and sync the agent frontmatter:

1. **Validate** the candidate at the cheaper tier (set `settings.models`, run the role's Tier-2 gate;
   it must clear `mean − stddev ≥ 0.8` at that tier). Record the numbers.
2. **Promote** — edit `models.VALIDATED_TIERS[<role>]` to the validated tier (e.g. `"grader":
   "cheap"`). This is the committed runtime policy that ships with the agents.
3. **Sync** — `python dev/sync_models.py --apply` rewrites each agent's `model:` frontmatter from the
   policy (`default` → `inherit`, else the concrete model id).
4. **Gate** — `python dev/validate.py` (Tier-0) **enforces** frontmatter == policy, so a drift or an
   un-synced promotion fails the build. `dev/sync_models.py` (no `--apply`) is the CI-friendly check.

The committed policy ships **all-`default`** (every agent `model: inherit`), so there is no runtime
downgrade until you deliberately promote one through this gated flow.

## Recording results

Tier-2 numbers are run artifacts, not contract fields, so they are not committed into
`evals.json`. After a run, record the achieved `mean`/`stddev`/`lower_bound`/`n` per role in
the CHANGELOG entry (or a milestone note) next to the thresholds, per the eval-loop guide
("record the final numbers"). If a role misses the bar, improve its prompt/return contract
and re-run. Tier-2 numbers are model-dependent — record which model produced them (current
baseline: `claude-opus-4-8`).

The latest skill Tier-2 baseline (the ADR-0020 fidelity pass) is recorded in the `CHANGELOG.md`
"Tier-2 eval fidelity" entry: the 7 reframed/improved gates are proven at **n = 5** (all clear
`mean − stddev ≥ 0.8`) on `claude-opus-4-8`; the 5 hardened packs scored **1.000 on a 1× re-check**
after the faithful reframe (they already cleared the bar at n = 5 in the prior live run).

## Validating the PR watcher (manual, live)

The PR watcher's deterministic core is unit-tested; the live `gh` / `git` / agent seams need a real
PR and `gh` auth, so validate them by hand once before enabling the scheduled job. Use a **throwaway
PR on a repo you own** — never a real PR first.

1. **Auth + scope.** `gh auth status` must be logged in with `repo` scope; the watcher pushes to the
   PR branch and posts comments as you.
2. **Dry plan (no writes).** From the repo:
   `python plugin/bin/pr_watch.py --owner <you> --name <repo> --pr <N>` — confirm it prints the actionable
   thread count + `conflicting=<bool>` and the thread ids, and makes **no** writes (check GitHub).
3. **Enable + apply on the throwaway PR.** Set `{"pr_watcher": {"enabled": true}}` in
   `.agentic-forge/config.json`, `gh pr checkout <N>`, then run with `--apply` and verify each
   invariant on the real PR:
   - a fixable comment → a commit on the branch + a reply + the thread **resolved**;
   - a comment it rejects → a reasoned reply, thread **left open**, no spurious commit;
   - a merge conflict → base **merged** into the branch and pushed (no force-push), or a single
     "please rebase" comment if it couldn't; **never a force-push or a PR merge/close** (verify via
     the PR timeline + `git reflog`);
   - every outward action appears in `~/.agentic-forge/state/<repo-slug>/diagnostics.jsonl` (audited even if diagnostics
     is off).
4. **Idempotency.** Re-run `--apply` with nothing new → **no** writes (resolved / bot-authored
   threads skipped; a still-conflicted PR does **not** get a second "please rebase" comment).
5. **Fork PR.** Point `--apply` at a fork PR → it must **refuse** ("same-repo auto-apply only") while
   the dry plan still works.
6. **Scheduled wiring.** Add the repo to `pr_watcher.repos`, run
   `python plugin/bin/run_scheduled.py run --repo . --force`, and confirm the `pr-watch` job fans out over
   the configured repos' open PRs (and no-ops with a message when disabled / no repos).

Enable the hourly cron only after all six pass — and only for repos whose PR authors you trust (the
auto-fix autonomy applies to every open same-repo PR).

## Caveats

- If `ANTHROPIC_API_KEY` is set, the `claude` CLI uses it before the subscription token —
  unset it for subscription billing.
- Level 1 (`--runner api`) cannot verify assertions that require real execution (e.g. "the
  tests are run and reported as passing") and under-credits write roles whose proof lands on
  disk; for `software-engineer`/`architect` use level 2 (`--runner claude`).
- The `claude` runner's `--allowedTools` are taken from the role's frontmatter; adjust the
  flags in `dev/run_agent_evals.py` if your CLI version expects a different format.
- Results vary run to run; the gate intentionally uses the lower bound over `n ≥ 5` runs to
  absorb that noise.
