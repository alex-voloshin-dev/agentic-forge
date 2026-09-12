---
type: release
feature: agentic-forge-2026.9.2
status: final
version: 2026.9.2
date: 2026-09-12
changelog:
  - "Fixed: a scheduled `eval.yml` run now FAILS when `CLAUDE_CODE_OAUTH_TOKEN` is absent (ADR 0082) — every model-backed Tier-1/2/3 step is gated on that token, so for months the weekly guard finished green in 23-32 seconds having checked no threshold at all. Every run also writes to its job summary which tiers it actually measured, and `CLAUDE.md` states the condition instead of claiming the cron unconditionally"
  - "Fixed: `resolve_gate` falls back `python` -> `python3` after the project-local bins and `PATH` — 78 of this repo's 96 diagnostic records are one `FileNotFoundError: 'python'` on a host that has only `python3`, i.e. the Tier-0 gate was off on the machine that develops the plugin"
  - "Fixed: `session_coverage` counts inside the audit log's retained window and reports older sessions as rotated out (ADR 0082) — the production repo's bundle read '9/12 — 3 MISSED (a hook may not have logged them)' against a log that physically retains 13 days, and the same check called this repo '2/2 complete' with ten sessions logged and three transcripts on disk"
  - "Changed: a `TimeoutExpired` fail-open says the gate timed out and points at scoping the lint or gating in CI, instead of telling the operator to install a tool that is installed and working"
  - "Measured (no code change): Tier-1 re-run live for `marketing`, `product`, `research`, `ux-design` — all four at recall 1.000 / specificity 1.000, against July records of 0.72-0.84. No description was re-tuned"
breaking: []
---

# Release 2026.9.2

The second 2026-09 bundle is the first to carry **two** repositories: this plugin developing itself
(3,246 tool calls) and `softico-web`, an unrelated production Next.js project the plugin works on
but did not author (13,585). Read together, both halves say the same sentence three times —
something reported success, nothing was measured.

## A guard that could not fail

`CLAUDE.md` promised a weekly cron that re-runs Tier-1 "so a routing regression surfaces". The last
six scheduled runs finished **success in 23-32 seconds**, with every model-backed step skipped for
a missing subscription token. The wiring resolved; no threshold was ever checked. A green tick
meaning "contracts parse" was indistinguishable from one meaning "recall is above 0.9".

What that guard was hiding sat in this repo's own diagnostics log: July Tier-1 recall of 0.750
(`ux-design`), 0.720-0.840 (`product`), 0.800 (`research`), 0.822 (`marketing`) — the same
doc-phase skills ADR 0081 had recorded as never firing in the field.

## So the measurement was taken, not assumed

Tier-1, live against the listing, five runs each, on the day of this release:

| skill | July | now |
|---|---|---|
| `marketing` | 0.822 | **1.000** / 1.000 |
| `product` | 0.720-0.840 | **1.000** / 1.000 |
| `research` | 0.800 | **1.000** / 1.000 |
| `ux-design` | 0.750 | **1.000** / 1.000 |

**No description was changed.** The July failures were real when recorded and had been fixed in
passing by the 2026.7.x description work; nobody could tell, because the diagnostics channel writes
only failures and the CI that would have re-measured was skipping the step. Two months of a
resolved problem looking unresolved, and a blind guard reporting success over it.

It also sharpens the open question from 2026.9.1. Recall is **perfect** for exactly the skills that
did not fire once in 27 days of field work. The router routes correctly when it is asked; in the
field it was not asked. That is a matter for a Tier-1 condition carrying a competing project
instruction — not for a better description — and it stays on the roadmap.

## The gate was off on the machine that develops the plugin

78 of this repo's 96 diagnostic records: `FileNotFoundError: [Errno 2] No such file or directory:
'python'`, gate `python dev/validate.py`. A modern macOS has `python3` and no `python`. ADR 0081's
project-first resolution happened to hide this here by finding `.venv/bin/python`; a repo without a
virtualenv was still ungated. The resolver now knows that one naming split.

## The coverage check was inventing holes

`softico-web`'s bundle reported "9/12 — 3 MISSED (a hook may not have logged them)". No hook failed:
that audit log physically retains thirteen days after three rotations discarded 17 MB, while the
transcripts it is compared against go back months. The same check called this repo "2/2 complete"
with ten sessions in its log and three transcripts surviving on disk. It compared two collections
with different retention policies and reported the difference as a hook failure, in whichever
direction it fell. It now counts inside the retained window and names rotated-out sessions as such.

## What worked

- **The gate does its job on code it did not write.** All seven blocks in `softico-web` are genuine
  eslint failures with file and line — none of the "missing script / broken environment" class.
- **Zero security-hook false positives** across 13,585 tool calls on the production repo.
- **No secrets** in either log on a re-scan, on a workload that handles real credentials daily.
- The one `NameError` in the log is four minutes older than release 2026.7.10 and was fixed by the
  commit that introduced it; `ruff` (F821) covers that class in Tier-0.

## Verification

- `python dev/validate.py` — Tier-0 clean; `pytest` green at 97.8% coverage; `ruff`, `mypy` clean.
- `python dev/run_tier1_evals.py --runner claude --model claude-opus-4-8 --skill product --skill
  research --skill marketing --skill ux-design` — 4/4 PASS at 1.000/1.000.
