---
type: release
feature: agentic-forge-2026.11.16
status: final
version: 2026.11.16
date: 2026-11-25
changelog:
  - "grader and qa-engineer run on claude-sonnet-5-5 after Tier-2 at Opus 5.5 and Sonnet 5.5; the other four roles stay inherit because the sets do not separate the tiers (ADR 0114)."
  - "TIERS is the 5.5 family and every eval CLI and pr_watch default to TIERS['default']; the Tier-2 judge is held fixed (--grader-model), recorded in the history, and a default run measures promoted roles at their shipped tier."
  - "Roles and stack packs name af.py stack-detect instead of the stacks library calls (ADR 0104 follow-up)."
  - "The external reviewer lens names a read-only CODEX_HOME at codex start-up as the cause, and what the lens needs (field item 9)."
breaking: []
---
# Release 2026.11.16

Open item 6, step 3 (ADR 0114), with the owner's go for live eval runs; a cleanup that closes an ADR 0104 residual; and
field item 9 (thread 1238c62d).

## What changed

- **Two roles run on Sonnet 5.5.** All six roles were measured at Tier-2 (n = 5) on Opus 5.5 and on Sonnet 5.5, judged by
  Opus 5.5 both times:

  | Role | Opus 5.5 | Sonnet 5.5 |
  | --- | --- | --- |
  | reviewer | 0.971 ± 0.039 | 1.000 |
  | security-engineer | 1.000 | 1.000 |
  | architect | 1.000 | 1.000 |
  | grader | 1.000 | 1.000 |
  | qa-engineer | 0.982 ± 0.041 | 1.000 |
  | software-engineer | 1.000 | 1.000 |

  Every role clears the gate at both tiers, so the sets do not separate the tiers. `grader` and `qa-engineer` move to
  `simple` (`model: claude-sonnet-5-5`; qa's output is checked by execution and sits behind the review lenses);
  `reviewer`, `security-engineer`, `architect` and `software-engineer` stay `inherit` until harder cases can tell the
  tiers apart. The full id, not the `sonnet` alias, because on Bedrock and Vertex the alias maps to an older Sonnet.
  `CLAUDE_CODE_SUBAGENT_MODEL` with `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` overrides it for a user who wants one model.
- **The tier table is the 5.5 family** (`claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`), and every eval CLI
  and `pr_watch` default to `TIERS["default"]`.
- **The Tier-2 judge is held still.** The runners graded on the component's tier, so a cheaper tier changed the
  instrument too. They now grade on `--grader-model` (default `--model`); the history records the judge and the
  version-over-version check compares only runs with the same judge. A default role run measures a promoted role at its
  shipped tier.
- **Roles and stack packs name `af.py stack-detect`** instead of the library calls a plugin-only install cannot import;
  a test fails if a role, skill or pattern names them again. Both changed roles were re-measured afterwards
  (software-engineer at Opus 5.5 1.000, qa-engineer at Sonnet 5.5 1.000).
- **A failed external lens on a read-only home says why.** When codex cannot start because its `CODEX_HOME` is
  read-only (a host sandbox), the failure line ends with a fixed hint: the lens needs a writable `CODEX_HOME`, the
  in-session lenses are unaffected. Only a codex start-up line counts (codex's own read-only sandbox prints the same
  error whenever the model tries a write); reasons and exit codes are unchanged, nothing touches `CODEX_HOME`.

## How it was checked

- ADR 0114 branch: two review rounds (reviewer: changes, then approve; codex: changes, then approve). Item 9: two rounds
  (reviewer changes then approve with a minor applied; codex approve, its round-2 minor applied: the non-fatal
  PATH-aliases warning no longer triggers the hint). The stack-detect cleanup was reviewed inside the ADR 0114 branch.
  Details in `review-code-2.md`.
- Live: Tier-2 for all six roles at two models (12 runs of n = 5), plus two re-runs after the role text changed.
- Tier-0: `dev/validate.py`, `ruff`, `mypy`, the full pytest suite, `dev/hook_smoke.py` under Python 3.9.

## Not validated

- Tier-1, Tier-1b: no skill description and no routing text changed; not run.
- Tier-3 (spine): not run.
- Skill Tier-2: not run (no skill body changed except the one-line stack-detect wording in ten packs).
- Whether a subagent whose model the account cannot use fails or falls back is not documented; a Foundry user needs a
  `claude-sonnet-5-5` deployment or `modelOverrides` entry, or the force variables above.

## Still open (item 6)

- Harder, discriminating Tier-2 cases before promoting reviewer, security-engineer, architect, software-engineer.
- `reader` / `clerk` roles and a routing-note sentence (Tier-2, Tier-1b).
- An `omitClaudeMd` A/B for the review lenses (the harness must learn to apply the field first).
