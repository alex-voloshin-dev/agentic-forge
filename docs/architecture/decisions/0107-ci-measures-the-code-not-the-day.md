# ADR 0107 — CI measures the code, not the day's tool releases

Status: Accepted (implemented)
Date: 2026-11-11

Extends [0094](0094-the-audit-the-same-three-shapes-everywhere.md) (the Python 3.9 floor for hooks, tested in CI)
and [0083](0083-weekly-measures-routing-not-everything.md) (which CI job measures what).

## Context

A dependency review on 2026-11-11 found:

- `pyproject.toml` declared floors far below what the gate was run with: `pytest>=8.0`, `ruff>=0.5`, `mypy>=1.10`,
  `jsonschema>=4.21`, `setuptools>=68`, against 9.2, 0.17, 2.4, 4.26 and 84 installed.
- Nothing pinned what CI installs. Every run took whatever was newest that day, so a ruff minor release that adds a
  rule, or a mypy release that tightens inference, could turn CI red with no change to the code. That also means a
  green run did not say which tool versions passed.
- CI ran the dev tooling on Python 3.11 only. The maintainer's environment was 3.12; the newest release is 3.15.
- The workflows used `actions/checkout@v4`, `setup-python@v5` and `setup-node@v4`, two majors behind, and Node 20 for
  the Claude Code CLI, past its end of life.

## Decision

1. **Floors are the tested lines.** `pytest>=9.2`, `pytest-cov>=7.1`, `mypy>=2.4,<3`, `jsonschema>=4.26`,
   `pyyaml>=6.0.3`, `setuptools>=80`. ruff is pinned to its minor line, `>=0.17.4,<0.18`, because it adds rules in
   minor releases; moving to the next minor is a deliberate change that fixes or waives what the new rules find.
2. **CI installs from `constraints/ci.txt`.** The file pins every package the dev install pulls in. It is generated
   with `uv pip compile pyproject.toml --extra dev --universal --python-version 3.11`, so one file resolves for every
   supported interpreter. All workflows install with `pip install -c constraints/ci.txt -e ".[dev]"`. A dependency
   moves when someone regenerates the file and the gate passes, never because a release came out.
3. **The Tier-0 job runs on both ends of the supported range.** Python 3.11 (the floor in `requires-python`) and 3.15
   (the newest), as two steps inside the existing job. A matrix would rename the job, and the branch rules require the
   check by its name, "Tier 0 (static gate)". ruff and mypy run once, on 3.11; mypy targets 3.11 by configuration.
   The hooks job stays on 3.9 (ADR 0094).
4. **Actions move to v7** (`checkout`, `setup-python`, `setup-node`). Their breaking changes are the Node 24 runtime
   inside the actions, a credential file layout we do not read, fork checkouts refused for `pull_request_target`
   and `workflow_run`, which we do not use, and the removed `pip-install` input, which we do not use. The CLI's Node
   moves from 20 to 24.
5. **The maintainer's local `.venv` is built on 3.15 with `uv`**, from the same constraints file.

The optional `eval` extra (`anthropic>=0.39`, latest 2.x) is left out of this change. It needs an API-key run of
`--runner api` to verify, and is a separate step. It was done in [0108](0108-the-eval-extra-moves-to-anthropic-2.md).

## Consequences

- A red CI run on an unchanged tree now means the code or the platform broke, not a tool release.
- Updating a tool is a one-line regenerate plus a gate run, done on purpose and recorded as a commit.
- The constraints file can age. It is regenerated whenever a dependency is updated, and at least before a release
  that touches the dev tooling.
- Users of the plugin are not affected: the shipped plugin has no Python dependency pins of its own. PyYAML and
  jsonschema stay optional at runtime, and hooks stay on the standard library.
