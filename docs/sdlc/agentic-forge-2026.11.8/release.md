---
type: release
feature: agentic-forge-2026.11.8
status: final
version: 2026.11.8
date: 2026-11-11
changelog:
  - "CI installs from a pinned constraints file, so a tool release no longer changes what a run measures (ADR 0107)."
  - "pyproject floors raised to the tested lines; ruff held to its 0.17 minor."
  - "The required Tier-0 job gates Python 3.11 and 3.15 in one job; the hooks job stays on 3.9."
  - "GitHub Actions checkout, setup-python and setup-node move to v7; the Claude Code CLI's Node to 24."
breaking: []
---
# Release 2026.11.8

A maintenance release for contributors. Nothing in the shipped plugin changes: no skill, agent, hook or library file
is touched. It changes how the repository is built and checked.

Until now CI installed whatever tool versions were newest on the day it ran, and the floors in `pyproject.toml` were
far below what anyone tested with (`ruff>=0.5` against 0.17, `mypy>=1.10` against 2.4). A new ruff or mypy release
could turn CI red with no change to the code, and a green run did not record which versions passed.

## What changed

- **`constraints/ci.txt`** pins every package the dev install pulls in. It is generated with
  `uv pip compile pyproject.toml --extra dev --universal --python-version 3.11`, so one file resolves for Python 3.11
  through 3.15. Every workflow installs with `pip install -c constraints/ci.txt -e ".[dev]"`.
- **Floors** in `pyproject.toml` are the tested lines: pytest 9.2, pytest-cov 7.1, mypy 2.4 (below 3), jsonschema 4.26,
  PyYAML 6.0.3, setuptools 80. ruff is held to `>=0.17.4,<0.18`, because it adds rules in minor releases.
- **"Tier 0 (static gate)"** now runs the gate twice in one job: the full gate on Python 3.11, then validate and pytest
  on 3.15. A matrix would have renamed the check the branch rules require. The 3.9 hooks job is unchanged (ADR 0094).
- **Actions:** `checkout`, `setup-python` and `setup-node` move to v7. Their breaking changes (Node 24 inside the
  actions, a new credential file layout, refused fork checkouts on `pull_request_target`/`workflow_run`, a removed
  `pip-install` input) do not touch how these workflows use them. The Claude Code CLI in the eval jobs runs on Node 24.

## Upgrade notes

Plugin users: nothing to do. Contributors: rebuild your environment with
`uv venv --python 3.15 && uv pip install -c constraints/ci.txt -e ".[dev]"`, or the same with `pip`.

## Measured

- Python 3.11.18 from the constraints file: `dev/validate.py` clean (listing 6910/6910), ruff and mypy clean (63
  files), pytest green with coverage 95.86%.
- Python 3.15.2: the same gate green, coverage 95.86%; `dev/hook_smoke.py` passes.
- The new CI layout is measured by this release's own pull request.

## Not validated

- Tier-1, Tier-2 and Tier-3 were not run: no skill, agent or hook changed.
- The eval and scheduled workflows on v7 actions and Node 24 run only on their triggers (a label, dispatch or the
  weekly cron); their first run after this release is their check.

## Next

The optional `eval` extra (`anthropic>=0.39`, current 2.x) moves separately: it needs a `--runner api` run with an API
key. Then the queue: the external reviewer's 128 KiB limit, the vault's folder loading, the handoff readiness field
and stack detection.
