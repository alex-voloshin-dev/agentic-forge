# Meta-core (Layer 0) — how it works

Layer 0 is the foundation that builds and gates every other component. It is fully
implemented and green (Tier-0 validator, unit tests, lint, types). This document explains
each piece and how they fit together.

## Why it exists and the bootstrap order

`skill-factory` is meant to create every component "evals-first", but it cannot validate
itself before the validator and harness exist. To avoid the chicken-and-egg trap, the
meta-core is built bottom-up and deterministically:

1. **Skeleton + shared lib + Tier-0 validator** — hand-written, covered by `pytest`. No
   LLM involved, so it is testable by ordinary means.
2. **Eval-harness** — deterministic aggregation and gate logic; LLM judgment is external
   (skill-creator), so our logic is unit-tested with plain data.
3. **Contract schema** — `evals.json` superset; the readiness definition.
4. **`skill-factory`** — the only component whose evals are hand-written (the bootstrap
   exception). It is then dogfooded by using it to produce gate-passing components.

## Repository layout (built)

```
plugin/
  .claude-plugin/plugin.json          # plugin manifest
  skills/skill-factory/               # the meta-skill (L0 deliverable)
    SKILL.md  references/  assets/  evals/evals.json
  lib/agentic_forge/                  # shared, importable, tested
    naming.py frontmatter.py evals.py validation.py benchmark.py gate.py
    handoff.py agent_eval.py          # L1/eval-harness additions
    spine_e2e.py stacks.py            # L2 spine: Tier-3 E2E + by-stack detection
    tier1_runner.py skill_eval.py     # L2: skill Tier-1 (live listing) + skill Tier-2 runners
    activation.py                     # L2: skill Tier-1b (unprompted activation, ADR 0088)
    pre_router.py                     # L4: deterministic pre-router for the UserPromptSubmit hook (ADR 0089)
    vault.py                          # L3: Obsidian knowledge-vault core (ADR 0018)
    guardrails.py                     # L4: guardrail hook logic (ADR 0019)
    ops.py release.py                 # Stage 4: deploy/incident assessment + release core (ADR 0021)
    schedule.py observability.py      # Stage 7: scheduled-job registry + audit digest (ADR 0024)
    connectors.py                     # real provider connectors behind the ops seams (ADR 0025)
    skill_contract.py planning.py     # quality-hardening: handoff/recall guards + plan batches (ADR 0032/0034)
    diagnostics.py                    # opt-in self-diagnostics channel: errors/anomalies (ADR 0039)
    settings.py models.py             # plugin config (ADR 0041/0049) + model tiering/routing (ADR 0043/0046)
    external_review.py pr_watch.py pr_hook.py   # external-reviewer seam (ADR 0042) + PR-watcher core (ADR 0044/0045/0063)
    ralph.py                          # bounded autonomous Ralph-loop core (ADR 0048)
  schemas/{evals,config}.schema.json  # the component contract schema (superset) + the config schema
  eval/{README.md, fixtures/}         # harness architecture + agent eval fixtures (L1)
  hooks/{hooks.json, scripts/*.py}    # L3 session-start + L4 guardrail hooks (ADR 0018/0019)
dev/{validate.py, run_agent_evals.py, run_skill_evals.py, run_tier1_evals.py, run_activation_evals.py, run_spine_e2e.py, hook_smoke.py, audit_digest.py, diagnostics_digest.py, ralph.py, sync_models.py}  # maintainer + eval CLIs — NOT shipped
plugin/bin/{run_scheduled.py, pr_watch.py, external_review.py, state_migrate.py}  # runtime CLIs that DO ship to users (ADR 0072)
tests/                                # pytest for lib + harness + plugin integrity
pyproject.toml                        # uv / pytest / ruff / mypy config
.github/workflows/{ci.yml,eval.yml,scheduled.yml}  # Tier-0 + hooks-on-3.9 always; Tier-1 weekly, Tier-2/3 on demand; scheduled wiring smoke
```

## The shared library (`plugin/lib/agentic_forge/`)

| Module | Responsibility |
| --- | --- |
| `naming.py` | Validate skill names against the standard (1–64 chars, `a-z0-9-`, no leading/trailing/doubled hyphen, matches directory). |
| `frontmatter.py` | Parse YAML frontmatter into `(mapping, body)`; raise on missing/malformed blocks. |
| `evals.py` | Load `evals.json` and validate it against `schemas/evals.schema.json` (Draft-07). `fixture_dest` maps a `files` entry to its sandbox path: basename, or the path below a `tree/` segment (ADR 0094). |
| `validation.py` | Tier-0 checks for skills, agents, and the manifest; aggregate into a `Report`. `listing_budget`/`validate_listing_budget` measure the always-on listing (`- agentic-forge:<name>: <description>` per model-invocable skill) against `LISTING_BUDGET_CHARS` — a ratchet on growth, printed on every run, raised deliberately (ADR 0095). |
| `benchmark.py` | Aggregate per-run `grading.json` pass rates into a `benchmark.json` shape (mean/stddev/n, delta). `passed_value` reads the grader's `passed` in its spellings (`true`/`"pass"`/`"passed"`); the `sessions` block counts undetermined/ungraded runs (ADR 0094). |
| `gate.py` | Apply thresholds: `trigger_metrics`, `tier1_trigger`, `tier2_quality`, `evaluate`. Pure functions. `MAX_UNDETERMINED` (0.10): the share of sessions that never ran above which a gated run fails as a run, in every tier (ADR 0093/0094); `tier1_trigger` honours an optional contract `runs` floor. `tier2_evidence_lines` prints the failing assertions and one failing case's own words (ADR 0096/0098). |
| `handoff.py` | Load + validate SDLC handoff artifacts (Markdown + frontmatter) against per-type header schemas (L1). |
| `agent_eval.py` | Tier-2 quality runner for subagent roles, over a pluggable model seam (eval-harness; see ADR 0011); its `run_eval_cases` core is shared with the skill Tier-2 runner. `session_outcome` reads the `claude -p` envelope; `SessionUndetermined`/`TurnCapHit`/`SessionTimedOut` are raised at once (no retry for an answer, one for a timeout, backoff only for transport); an unparseable grading is *ungraded*, never a zero (ADR 0094). `sessions.failed_sample` keeps the first assertion-failing case's reply (run, case, 600 chars) so a FAIL says why without a re-run (ADR 0098). |
| `spine_e2e.py` | Tier-3 end-to-end runner — a `Scenario` registry (the SDLC `spine` + the `quality-gate` / `ops-incident` / `product-inception` / `market-brief` domain scenarios) carried through their phases on an isolated fixture copy, with deterministic per-phase checkpoints (L2; ADR 0030). The fixture's test suite is bounded (`TEST_TIMEOUT`, a named failed checkpoint on expiry); an undetermined phase fails a named checkpoint and later phases still run (ADR 0094). |
| `stacks.py` | Deterministic stack detection for target repos: `detect`/`primary` from hints/manifests plus the toolchain registry the spine's `develop`/`code-review` consume (by-stack; ADR 0015). `pack_path`/`pack_paths` resolve a pack to `skills/<pack>/SKILL.md`: off-listing packs are reached by `Read`, never by name (ADR 0094). |
| `tier1_runner.py` | Tier-1 trigger runner on the **live** skill listing: classify each on-listing skill's trigger prompts via the router, gate recall/specificity (ADR 0016). An off-format reply is `INVALID` — dropped from the denominator and reported, never mined for a skill name; an all-invalid prompt is `unmeasured` and fails (ADR 0064). Gates on the pooled never-ran share (`MAX_UNDETERMINED`; the router's own non-answers are reported, not capped) instead of a per-prompt half-rule; a namespaced spelling of our skill is ours; `n=` on every line (ADR 0094). |
| `activation.py` | **Tier-1b** activation runner (ADR 0088): run each skill's should_trigger prompts through a REAL Claude Code session with the plugin loaded and scan the transcript for a `Skill` tool call naming that skill — the fraction that fire unprompted, where Tier-1 only measures the router answering when asked. Gated on the rate **pooled** over the run (`pooled()`, `--min-activation 0.80` in CI — ADR 0093); the per-skill lines are a lens, since at 4-9 prompts a skill they cannot be a gate. A measurement when no floor is given. |
| `pre_router.py` | Deterministic pre-router (ADR 0089): on each prompt, IDF-weighted coverage of the prompt by each skill's profile (description ∪ trigger prompts, minus other skills' trigger vocabulary — the contrastive-clause leak) names the clearly-matching skill in `additionalContext`. Abstains on ambiguity; `self_check` is the leave-one-out calibration (recall 0.488 / precision 0.932 / wrong-skill 1, recalibrated in ADR 0092 at 0.40 / 0.15). Suggests only, never invokes. |
| `skill_eval.py` | Skill Tier-2 quality runner: knowledge skills run as the `software-engineer` with them loaded, others directly; reuses `agent_eval.run_eval_cases` (ADR 0017). |
| `vault.py` | L3 knowledge-vault core: parse/resolve `[[wikilinks]]`, load + validate the note graph, scaffold, add+link notes, rank recall candidates, build the session-start summary (ADR 0018). |
| `guardrails.py` | L4 guardrail logic: dangerous-command deny-list, test-gate command choice, secret redaction + audit record, subagent-budget counter (ADR 0019). |
| `ops.py` | Stage-4 ops assessment behind provider-agnostic `PipelineSource`/`AlertSource` seams: `rollout_health`, `triage_alerts`, `deploy_status`, `classify_incident` (sev1–4) (ADR 0021). `SourceUnavailable` is what a seam raises instead of `[]`; `deploy_status` carries `unavailable` and the `unknown` health — never "healthy" from no data (ADR 0094). `UnavailablePipeline` is a configured source that cannot answer and says why — distinct from an empty in-memory one (ADR 0095). |
| `release.py` | Stage-4 release core: classify conventional commits → semver bump + Keep-a-Changelog grouping; thin `commits_since` git seam (ADR 0021). |
| `schedule.py` | Stage-7 scheduled-job registry + pure `due_jobs` due-logic + last-run state I/O (ADR 0024). |
| `observability.py` | Stage-7 audit-log digest: parse the logging hook's JSONL → per-tool/session counts + report (ADR 0024); size-bounded rotation of the audit log **and** `diagnostics.jsonl` at session start, archives kept (ADR 0080/0081/0094). |
| `connectors.py` | Real provider connectors behind the `ops` seams: `GhPipelineSource`, `GrafanaAlertSource` — pure parsers + thin fetch seams (ADR 0025). `gh run list` is bounded (60 s); a failed, timed-out or non-JSON fetch raises `ops.SourceUnavailable` (ADR 0094). `slug_from_remote_url`/`remote_slug` resolve `owner/name` from a checkout's `origin`; `pipeline_source` takes a path *or* a slug and is `UnavailablePipeline` when `gh` is present without a GitHub remote (ADR 0095). |
| `skill_contract.py` | Guards on skill bodies: each artifact skill documents its handoff schema's required fields (`handoff_contract_problems`, ADR 0032), and each spine phase references the knowledge-recall step (`recall_problems`, ADR 0033). |
| `planning.py` | Pure dependency batching of plan tasks into topological levels (`plan_batches`) for parallel `develop` (ADR 0034). |
| `diagnostics.py` | Opt-in self-diagnostics channel: collect the plugin's *own* errors/denials/anomalies into a redacted, gitignored `diagnostics.jsonl` + pure `digest`/`render` (ADR 0039). Contrast `observability.py` (usage) — this is what went *wrong*. `hook_crash` records a hook's own crash regardless of the opt-in and announces it once per session; `hook_notice` is the one JSON shape a hook's warning takes (`systemMessage` + `additionalContext`) (ADR 0094). |
| `settings.py` | One resolver for the plugin's knobs over a layered precedence (built-in < user `~/.agentic-forge/config.json` < repo `.agentic-forge/config.json` < env); `resolve()` never raises, validates against `config.schema.json` (ADR 0041/0049); a dropped config is carried as `Settings.warnings` and announced once per session by SessionStart (ADR 0094). |
| `models.py` | Model tiering: resolve which model a component runs on (cheaper tiers for simpler work), opt-in via `settings.models` and gate-validated, mapping the validated tier to each agent's `model:` frontmatter (ADR 0043/0046). |
| `external_review.py` | External-reviewer seam: run a third-party reviewer CLI (codex) as an independent lens — pure `build_prompt`/`parse_review` + a thin subprocess seam that never raises (ADR 0042). |
| `pr_watch.py` | PR-watcher core: parse a GitHub PR's review state, drive the bounded fix loop over `gh`/`git`/fix seams, and gate the merge (`merge_readiness` — not draft, checks green, no unresolved threads, mergeable). Never force-pushes; merges only via an opt-in seam (ADR 0044/0045, autonomous mode 0063). A thread whose fixer session never ran is `undetermined`: nothing posted, retried next poll; `fixer_timeout` bounds one attempt under the watch budget; `reply_never_ran` recognises CLI/limit error text (ADR 0094). |
| `doc_delivery.py` | Document-phase delivery isolation: deterministic naming + argv for the shared feature worktree, branch, commit, push and PR (one worktree and one PR **per feature**, not per phase — otherwise the next phase cannot read what this one wrote). Slug validated, never force-pushes (ADR 0070). `proceed_plan` commits without pushing when the repo has no remote and pushes without a PR when `gh` is absent, saying so in the delivery line (ADR 0094). |
| `pr_hook.py` | PR-created detection for the PostToolUse hook: command-position match on `gh pr create` plus the printed PR URL, producing the autonomous-watch reminder (ADR 0063). |
| `ralph.py` | Bounded autonomous Ralph-loop core: the pure iteration state + continue/done/exhausted/stalled decision over injected run/done/progress seams; the live wiring is `dev/ralph.py` (ADR 0048). An unlaunchable `--done-cmd` or a non-git repo is an error (`DoneCommandError`/`RepoStateError`), not "not done"/"stalled" (ADR 0094). |
| `diag_bundle.py` | Diagnostics bundle packager: pure `plan_bundle` (redacted file manifest: logs, env, plugin/config metadata) + `filter_by_window` / `default_output_path` + a thin `build_bundle` zip seam — a consistent, shareable production-diagnostics artifact (last N days, default 7 → `~/Downloads`); shipped as the off-listing `diagnostics-bundle` skill (ADR 0052/0053). |

Everything here is dependency-light (pyyaml, jsonschema) and unit-tested. Skill scripts and
hooks import from this package.

## Tier-0 validator (`dev/validate.py`)

A CLI that walks `plugin/skills/*` and `plugin/agents/*.md` and runs `validation.py`. For
each skill it checks: directory/name rules, required non-empty `description` (≤1024), body
≤500 lines, that local (`references/`/`assets/`/`scripts/`) **and cross-tree (`](../...)`) links
resolve**, and that a valid `evals/evals.json` (with `component.type: skill`) exists. Each agent is
gated the same way: a sibling contract at `plugin/agents/evals/<name>.evals.json` with
`component.type: agent` is required. Errors fail the gate (exit 1); warnings (e.g. unknown
frontmatter field) never fail. Standard fields and documented Claude Code extension fields are both
recognized; anything else warns as a possible typo. It also runs the two **skill-body contract
guards** (`skill_contract`, ADR 0032/0033) over the present skills — documented handoff fields +
the spine recall step — so a single `validate.py` run enforces them (they also block via pytest).

Coverage and types are part of Tier 0 too, enforced in CI: `pytest --cov=agentic_forge
--cov-fail-under=80`, `ruff`, and `mypy` (see [ci.yml](../../.github/workflows/ci.yml)).

Run it:

```bash
python dev/validate.py            # validates ./plugin
python dev/validate.py <path>     # validates a specific plugin dir
```

## Eval harness (hybrid on skill-creator)

agentic-forge does not run or grade LLM evals itself — the official `skill-creator` loop
does that (isolated subagent runs, assertion grading to `grading.json`, timing capture).
The meta-core adds the **policy layer**:

- `benchmark.summarize(with_skill, without_skill, with_skill_timing=…, without_skill_timing=…)`
  turns `grading.json` (and optional per-run timing) lists into the aggregate `benchmark.json`
  shape, including the with/without pass-rate delta and the time overhead delta.
- `gate.tier2_quality(benchmark, thresholds)` passes only when the pass-rate **lower
  bound** `mean − stddev` over the required number of runs meets `min_pass_rate`, the with/without
  A-B lift meets `min_lift`, and the time and token overheads stay within `max_overhead_seconds` /
  `max_overhead_tokens`. Gating on the lower bound absorbs LLM run-to-run noise. *(The runners
  always capture per-run wall-clock timing; the skill runner's opt-in `--baseline` (ADR 0036)
  reruns each case without the skill to populate the with/without delta, and the transports report
  token usage via `RunOutput` (ADR 0038), so the `min_lift` / `max_overhead_seconds` /
  `max_overhead_tokens` branches are all live. Version-over-version A-B is also live now (ADR 0047):
  `gate.version_regression` compares a run against a stored `benchmark` history record and FAILs on a
  `max_regression` drop, wired into both runners via `--record` / `--benchmark-history`. Pass-rate is
  the always-on Tier-2 gate.)*
- `gate.trigger_metrics(...)` + `gate.tier1_trigger(...)` score auto-loading: recall over
  should-trigger prompts, specificity over should-not-trigger prompts.

See [../../plugin/eval/README.md](../../plugin/eval/README.md) for the full division of
labour and flow.

## The contract: single-file `evals.json` superset

Each component ships exactly one `evals/evals.json`, a **superset** of the skill-creator
format (`schemas/evals.schema.json`):

- `skill_name`, `evals[]` (`id`, `prompt`, `expected_output`, `files`, `assertions[]` as
  strings) — read by skill-creator.
- `component` (`id`, `type`, `purpose`), `thresholds` (tier1/tier2/tier3), `triggers`
  (should/should-not) — read by agentic-forge; ignored by skill-creator.

One file, two consumers. The schema requires the superset keys and rejects malformed
contracts, so Tier-0 enforces "evals exist and are well-formed" before any body is judged.

## `skill-factory` (the meta-skill)

A router-pattern skill: a lean `SKILL.md` (well under the 500-line cap) plus references per component type
(`skill.md`, `agent.md`, `script.md`) and the `eval-loop.md` guide, with templates in
`assets/`. It encodes the standing process — **contract → evals → implementation → gate** —
and refuses to write a component body before its `evals/evals.json` exists. v1 builds
skills, subagents, and Python scripts.

Its own `evals/evals.json` is hand-written (the bootstrap exception — every other component
gets its evals via `skill-factory`). It declares the standard Tier-1/Tier-2 thresholds and
is gated like any skill once the skill-creator loop is run against it; today it is enforced
at Tier 0, and the plugin-integrity test dogfoods that the whole plugin passes its own
Tier-0 gate.

## CI

- `ci.yml` runs the Tier-0 gate on every push/PR: `validate`, `pytest`, `ruff`, `mypy` — plus
  `hooks-py39`, which compiles, imports and smoke-runs every hook under **Python 3.9** with nothing
  installed (`dev/hook_smoke.py`): the floor a stock macOS `python3` gives the field, tested rather
  than assumed, because a hook that cannot start fails open and silent (ADR 0094).
- `eval.yml` runs three jobs (ADR 0083): `wiring` on every trigger; `trigger` — Tier-1 routing —
  on the **weekly cron**, on dispatch and on the `eval` label, failing when the token is missing
  (ADR 0082); `quality` — Tier-2 + Tier-3 — on demand only. The dispatch input `tiers` (`all` /
  `trigger-only` / `builtins-condition` / `activation`) maps each value to exactly one path, by
  positive list; `activation` runs Tier-1b gated at pooled ≥ 0.80 (ADR 0093), and the job summary
  names the step that ran. Model-backed steps use a Claude **subscription** token
  (`CLAUDE_CODE_OAUTH_TOKEN`) via the `claude` CLI and deliberately leave `ANTHROPIC_API_KEY`
  unset (it would override the subscription); skills are run by `dev/run_skill_evals.py`
  (ADR 0017), and the optional `--runner api` path uses `ANTHROPIC_API_KEY`. `scheduled.yml` is a
  wiring smoke for the scheduled entry point. Expensive LLM evals stay off the always-on path.

## How to extend

Use `skill-factory`: load the plugin in a Claude Code session (`claude --plugin-dir
plugin`), then describe the component — `skill-factory` auto-loads and writes the contract
and evals first, before you implement and run the gate (see
[handoff-to-cli.md](../handoff-to-cli.md) §4). The plugin-integrity test guarantees nothing
merges that breaks Tier-0.
