---
type: release
feature: agentic-forge-2026.11.5
status: final
version: 2026.11.5
date: 2026-11-03
changelog:
  - "Security: skills and patterns run a shipped script, `python3 -E \"${CLAUDE_PLUGIN_ROOT}/bin/af.py\"`, instead of inline `python -c`, which a repository could shadow to run its code."
  - "Security: git calls refuse a repo-shaped subdirectory's config, YAML aliases are refused in artifacts, and committed inputs are capped."
  - "Security: `pr-watch` prints no push or merge for a fork, a PR outside the checkout's origin, or an author without write access, and pushes before it replies or resolves."
  - "Fixed: `deploy-status` no longer reads healthy from what it did not read, health is per workflow, and a cancelled run is not a pass."
  - "Fixed: a phase on `proceed` sets `status: approved`, an approved verdict with a red gate escalates at the cap, and `release` works with non-conventional commits."
  - "Changed: the skills work on a plugin-only install, and new vault notes quote their titles and tags."
breaking:
  - "`deploy-status` reads `unknown` with no `gh` or when a set alert source fails, and health can change where a green run of another workflow used to hide a failure."
  - "`vault-validate` exits 1 when it finds problems, and note names `moc` and `readme` are refused."
---
# Release 2026.11.5

Skills stop telling the model to run inline Python. A repository could replace the module that command imported and run its code as you,
from a fresh clone, with no setting involved. Running the skills' flows from top to bottom for this change also found older problems in them,
and those are fixed here.

## Upgrade notes

Upgrade from any earlier version.

- A plugin-only install now works without `agentic_forge` being importable. Without PyYAML or jsonschema, `handoff-load` exits 3 and the phase
  stops and reports it rather than guessing.
- **`deploy-status`:** with no `gh`, or an alert source that is set and fails, it reads `unknown`. With `gh` and no alert source the pipeline's
  reading stands, and the report says the alerts were not read. Health uses the latest run of each workflow, and a cancelled run is `degraded`.
- **`pr-watch`:** the skill now pushes first, then replies and resolves. It offers no push for a fork, a PR outside this checkout's `origin`, or
  a HEAD not on the PR's branch.
- `vault-validate` exits 1 when it finds problems. Note names `moc` and `readme` are refused.
- **Requires git 2.24 or later** for `git log --end-of-options`.

## Measured

- Tier-0: `dev/validate.py`, ruff and mypy clean; 3686 tests pass, coverage 95.60%. `dev/hook_smoke.py` passes on Python 3.12 and real 3.9.25.
  CI's Tier-0 and Python 3.9 jobs are required before merge.
- **Tier-2, real model `claude-opus-4-8`, N=5:** knowledge 1.000, pr-watch 1.000, incident-response 1.000, deploy-watch 1.000, release 1.000,
  diagnostics-bundle 1.000, deep-review 1.000, marketing 0.993, ux-design 0.971, repo-onboarding 0.956. All pass.
- **Tier-3, real model:** spine, quality-gate, ops-incident, product-inception and market-brief all pass.
- `ux-design` first failed its run because 3 of 15 sessions hit the 40-turn cap, without a quality failure. The cap was not raised: the skill now
  says its listed fields are the whole schema. The re-run passed with none hitting it.
- Planted repo modules did not run through any of the 21 commands under `PYTHONPATH=.` with `-E`.
- Reviews: two rounds with reviewer, security-engineer and external codex lenses. The last round's fixes and the `deploy-status` decision on a
  missing alert source had the unit gate and the evals above, not another review round.

## Not validated

- **Tier-1 and Tier-1b were not run.** No description changed. Tier-2 ran on the ten skills whose flows changed most, not on the other eight
  whose bodies changed: architecture, plan, research, product, code-review, develop, qa-test-strategy and security-review are covered through
  Tier-3 or not at all. Roles were not re-run.
- Real `gh` writes, Grafana, macOS, Windows, a case-insensitive filesystem, and how `${CLAUDE_PLUGIN_ROOT}` behaves in a file read with `Read`.
- In two diagnostic `ux-design` sessions the external reviewer was not invoked, against one of two on the old text. That sample is too small to
  conclude anything, so watch for it in real use.

## Known limits and follow-ups

Recorded in ADR 0104. A session can still write `python -c` on its own or leave out `-E`, and `hooks.json` runs without `-E`. Literal git lines
in skill bodies do not carry the bare-repository setting. Health does not know a run's branch. Roles and stack packs still name `stacks.detect`.
A tracked `.venv/bin/ruff` or `dev/validate.py` still runs through the commit gate as it always has, which needs its own decision.
