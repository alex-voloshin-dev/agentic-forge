---
type: release
feature: agentic-forge-2026.7.4
status: final
version: 2026.7.4
date: 2026-07-25
changelog:
  - "Fixed: commit-gate no longer fails open on genuine gate failures — the 'gate can't run' match dropped the over-broad `not found` / `no such file` substrings (which appear in real pytest/eslint/HTTP/gcc failures and this repo's own dev/validate.py `SKILL.md not found`) and now uses specific signatures plus shell exit code 127/126; real failures block again (ADR 0059, fixes an 0058 regression)"
  - "Fixed: commit-gate joins stdout/stderr with a newline so a signature can't be formed/destroyed across the stream boundary (ADR 0059)"
  - "Fixed: diagnostics bundle tolerates a non-UTF-8 transcript byte (_read_transcript_sessions reads with errors='replace'; UnicodeDecodeError no longer crashes the build) (ADR 0059)"
  - "Fixed: CI gate workflow triggers on master (was main, a non-existent branch — post-merge CI never ran)"
  - "Fixed: marketplace descriptor synced — version 0.0.1 → 2026.7.4 and the description lists the full domain set"
  - "Fixed: docs — README uses the real GitHub owner; broken ADR 0048 relative link corrected; 2026.7.3 product-agnostic cleanup documented in its changelog section"
breaking: []
---

# Release 2026.7.4

A hotfix release cut from the **pre-publication deep review** (five adversarial lenses over the whole
working tree, every finding verified against source). It corrects one real defect introduced in
2026.7.3 plus a set of public-repo hygiene issues found before flipping the repo public.

## Why a hotfix

The deep review found that 2026.7.3's commit-gate change (ADR 0058) matched a **bare `not found`**
to decide "the gate couldn't run" — but that substring also appears in *genuine* gate failures
(pytest `fixture 'x' not found`, eslint `'y' not found`, an HTTP `404 Not Found`, gcc `No such file
or directory`, and even this repo's own `dev/validate.py` `SKILL.md not found`). The effect was a
guardrail regression: a real failing gate was downgraded to fail-open and the commit allowed.
ADR 0059 tightens detection to specific signatures + shell exit code 127/126, so real failures block
again while a missing-script / uninstalled-linter still fails open.

## Scope

Two commits since `v2026.7.3`:
- `<deep-review fixes>` — ADR 0059 (commit-gate precision + stream separation + bundle UTF-8
  robustness) with regression tests.
- `<hygiene fixes>` — CI branch `main`→`master`, marketplace version/description sync, README owner,
  ADR 0048 link, CHANGELOG 2026.7.3 product-agnostic entry.

Curated entries live in `CHANGELOG.md` under `[2026.7.4]`. No API-breaking changes; all fixes.

## Verification

- Tier-0 `dev/validate.py` OK; `pytest` green (coverage ≥ 80%); `ruff`/`mypy` clean.
- Regression tests added: `gate_unrunnable` returns `False` for the five real-failure outputs
  (SKILL.md / pytest / eslint / HTTP / gcc); the commit-gate exit-code fail-open path (127); a
  bad-UTF-8 transcript that must not crash the bundle.
- The fix was checked against the original field bundle's diagnostics: the 10 real events
  (`Missing script` / `command not found`) still resolve to fail-open, while the new false-positive
  cases now correctly block.

## Tag

`v2026.7.4` (annotated), to be created on the merged master commit after the PR's rebase merge, per
CONTRIBUTING's "Cutting a release".
