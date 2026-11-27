---
type: release
feature: agentic-forge-2026.11.21
status: final
version: 2026.11.21
date: 2026-11-27
changelog:
  - "The security-engineer lens no longer loads the project's CLAUDE.md (omitClaudeMd: true) after a probe-validated A/B with no loss and 16 % lower cost; reviewer keeps it (ADR 0113 amendment)."
  - "New reader role: a read-only, role_scope-held subagent for bulk reading that returns anchored facts within a line cap and never quotes a secret; the clerk role is deferred until role_scope holds it (ADR 0116)."
  - "The agent-eval harness applies omitClaudeMd and runs a probe-validated A/B (--omit-claude-md, --claude-md, input fingerprints, prompt-token and cost reporting) (ADR 0113 amendment)."
  - "Harder, discriminating Tier-2 cases for reviewer, security-engineer, architect and software-engineer; the live run at both tiers moved no role (ADR 0114 amendment)."
  - "Every hook and shipped CLI resolves git and gh like the commit gate: absolute PATH entries only, .exe/.com only on Windows (ADR 0115 amendment 2)."
  - "Eval harness: fixture paths may not leave the plugin directory or the workspace; an eval case may ask for its own workspace; --runner api skips workspace cases per component."
breaking: []
---
# Release 2026.11.21

Field item 6, the rest (threads 1212fbfd, 3c001b52), plus the open follow-ups that could be closed. They are batched
into one release to save test runs.

## What changed

- **`security-engineer` runs without the project's CLAUDE.md** (`omitClaudeMd: true`, ADR 0113 amendment).
  - **The A/B.** Opus 5.5, n = 5, with a project CLAUDE.md in every workspace. A one-turn probe confirmed per arm
    that the file was loaded (`off`) or omitted (`on`).
  - **security-engineer.** 1.000 with the file and 1.000 without it, at 16 % lower cost per run. The `on` arm's
    transcripts show no read of the file.
  - **reviewer keeps CLAUDE.md.** In its `on` arm the role read the file anyway as a plain file, so that arm measured
    nothing; it scored 0.986 against 1.000.
- **New `reader` role** (ADR 0116). It is the default subagent for the cheap-delegation pattern's bulk reading.
  - **Held read-only.** It has Read, Grep and Glob only, held by `role_scope` like the grader.
  - **Its answer.** It returns only the facts the brief asks for, anchored to file:line, within a line cap. It says
    "not found" rather than guessing.
  - **Secrets.** It reports a secret by kind and anchor, never its value, and never opens credential files.
  - **Settings.** `omitClaudeMd: true`, `model: inherit`. Tier-2: 1.000 at Opus 5.5, n = 5.
  - **The `clerk` role is deferred.** Its limits would be prompt text only, and its worktree self-check can misfire
    when the caller itself runs in a linked worktree. ADR 0116 lists what it needs first, starting with a `role_scope`
    hold.
- **Harder Tier-2 cases** for reviewer, security-engineer, architect and software-engineer: two each, with their
  claims executed offline by `tests/test_tier2_hard_fixtures.py`.
  - **Results** at both tiers, Sonnet / Opus:

    | Role | Sonnet 5.5 | Opus 5.5 |
    |---|---|---|
    | reviewer | 0.992 | 0.977 |
    | architect | 1.000 | 1.000 |
    | software-engineer | 0.993 | 0.986 |
    | security-engineer | 0.925 ± 0.075 | 0.992 |

  - **No role moves.** Three sets still do not separate the tiers. Security case 5 drew false majors at Sonnet in 3
    of 5 runs.
- **The agent-eval harness applies `omitClaudeMd`** (ADR 0113 amendment).
  - `--omit-claude-md {role,on,off}` and `--claude-md <file>`.
  - Prompt-token (with cache) and cost figures per run.
  - A per-arm probe that decides an A/B's validity, arms paired only on an equal input fingerprint, and an invalid
    arm never recorded as a baseline.
- **git and gh are found by the gate's trusted lookup everywhere** (ADR 0115 amendment 2). This covers every hook and
  every shipped CLI (`af.py`, `pr_watch.py`, `run_scheduled.py`, `state_migrate.py`, `connectors`, `doc_delivery`,
  `release`).
  - **The lookup.** Absolute PATH entries only; on Windows only `.exe`/`.com`. Each site keeps its old answer when
    nothing is found.
  - **The merge gate changed in one case.** A relative PATH entry before an absolute one is now skipped, not refused.
- **Eval-harness safety.**
  - A fixture path may not leave the plugin directory or the workspace. This is checked on the live path, before any
    write or model call.
  - An eval case may ask for its own fresh workspace.
  - `--runner api` skips the components with workspace cases and runs the rest.
- **Docs.** CLAUDE.md and the eval workflow's comments now count seven roles with a Tier-2 set, and about 420 agent
  sessions for the on-demand quality suite. These are text-only edits, made with the owner's go.

## How it was checked

- **Review**, for each part:
  - Harder cases: reviewer, two rounds, then approve; codex approve.
  - `reader`: reviewer, security engineer and codex, three rounds. Their findings were applied, and the `clerk` was
    split out.
  - `omitClaudeMd` harness: four rounds; the fourth was approved by the owner. Codex approves.
  - Windows lookups: security engineer and codex. Details in `review-code-1.md`.
- **Live evals:**
  - Tier-2 of the four roles at both tiers on the extended sets.
  - Tier-2 of `reader` at Opus.
  - The `omitClaudeMd` A/B for reviewer and security-engineer.
- **Tier-0:** `dev/validate.py`, `ruff`, `mypy`, the full pytest suite, `dev/hook_smoke.py` under Python 3.9, and the
  dry runs.

## Not validated

- **`reader` at Sonnet.** Not run; the role stays `model: inherit`.
- **The `omitClaudeMd` A/B on the extended sets.** It ran on the original three-case sets.
- **Whether the security lens misses a project-specific rule** in a real repository without CLAUDE.md.
- **Tier-3.** No scenario was re-run live; no skill body changed. `spine`, `quality-gate`, `ops-incident` and
  `market-brief` have not been re-run live since the checkpoint change in 2026.11.20.
- **Windows.** The lookups are tested by simulation, not on a Windows host.
- **Delegation.** Whether sessions delegate to `reader` in practice: no harness counts it.

## Known limits

- **The `clerk` role is deferred** (ADR 0116 lists its requirements). Mechanical edits stay with a general-purpose
  subagent under the pattern's rules.
- **The maintainer eval harnesses** `spine_e2e` and `activation` still run git by bare name. They only run in repos the
  harness creates.
