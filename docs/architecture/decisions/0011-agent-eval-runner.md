# 0011 — Dedicated agent eval runner with a pluggable model seam

Status: Accepted

## Context

[ADR 0009](0009-engine-roles-and-handoff.md) said agents would be evaluated "with the
skill-creator subagent-run loop plus our gate". In practice skill-creator evaluates *skills*:
it compares runs with and without the skill and scores activation/triggering. Delegated
subagent roles have neither a with/without baseline nor a trigger surface, so skill-creator
does not apply to them. The `eval.yml` Tier-1/2 job was still a placeholder, so there was no
way to actually produce Tier-2 numbers for the four roles.

## Decision

Add a thin, dedicated **agent eval runner** (`plugin/lib/agentic_forge/agent_eval.py`, CLI
`dev/run_agent_evals.py`) that still reuses the agentic-forge policy layer:

- It runs each role on fixture tasks (`plugin/eval/fixtures/<role>/`, referenced from each
  case's `files`), grades the output with the `grader` role, aggregates with
  `benchmark.summarize`, and gates with `gate.tier2_quality` — the **same gate as skills**.
- The model/agent call is a **seam** (`Runner = (system, prompt, workdir) -> str`) with two
  production implementations: `api` (Anthropic Messages, level-1 fidelity) and `claude`
  (headless `claude -p` with the role's tools in a workdir, level-2 fidelity). The seam keeps
  the orchestration unit-tested with stubs; the real network/subprocess calls are excluded
  from coverage.
- **Auth: the `claude` runner is the default for real runs**, authenticating through the
  Claude Code CLI — a **Claude subscription** via `CLAUDE_CODE_OAUTH_TOKEN` (`claude
  setup-token`) or an API key. `api` is API-key-only. `ANTHROPIC_API_KEY` takes precedence
  over the subscription token, so it must be unset for subscription billing; grading also
  runs through the CLI so the whole run stays on the subscription.
- A `--runner dry` mode verifies wiring (contracts, role prompts, fixtures resolve) with no
  credentials and no model calls; it runs in CI on every eval job and is the local
  pre-flight check.

The Anthropic SDK is an optional `eval` extra, so the Tier-0 gate stays dependency-light.

## Alternatives considered

- **Force agents through skill-creator:** rejected — it is skill-shaped (with/without,
  activation); bending agents into it would be more work and less faithful than a thin runner.
- **A single fidelity level:** rejected — level 1 (Messages) cannot exercise file/test
  assertions for `implementer`/`architect`; level 2 (headless `claude`) can but needs the CLI
  and a workdir. The seam supports both, chosen per role/run.
- **Commit results into `evals.json`:** rejected — results are run artifacts; the contract
  stays the source of readiness. Numbers are recorded in the CHANGELOG/milestone notes.

## Consequences

- The four roles can be gated at Tier-2 for real (locally or in CI) without skill-creator.
- This narrows ADR 0009's "reuse skill-creator" for agents: skill-creator remains the engine
  for **skills**; **agents** use this runner. Both share the `benchmark` + `gate` policy
  layer, so the eval pyramid is unchanged.
- The level-2 (`claude`) seam depends on the `claude` CLI and the role's tool flags; its
  exact invocation may need tuning per CLI version (documented in the runbook).
