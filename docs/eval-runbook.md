# Eval runbook — Tier-2 quality for the engine roles

This explains how to run the Tier-2 (LLM-judged quality) evals for the six engine roles
(`reviewer`, `grader`, `software-engineer`, `architect`, `security-engineer`, `qa-engineer`)
and read the result. The orchestration is
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

## Recording results

Tier-2 numbers are run artifacts, not contract fields, so they are not committed into
`evals.json`. After a run, record the achieved `mean`/`stddev`/`lower_bound`/`n` per role in
the CHANGELOG entry (or a milestone note) next to the thresholds, per the eval-loop guide
("record the final numbers"). If a role misses the bar, improve its prompt/return contract
and re-run. Tier-2 numbers are model-dependent — record which model produced them (current
baseline: `claude-opus-4-8`).

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
