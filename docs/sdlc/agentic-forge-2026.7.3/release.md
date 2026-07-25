---
type: release
feature: agentic-forge-2026.7.3
status: final
version: 2026.7.3
date: 2026-07-25
changelog:
  - "Changed: external reviewer (codex, ADR 0042) on by default — external_reviewer.enabled defaults to true and is auto-wired as an extra lens into develop's code-review gate (--kind code) and product's skeptic pass (--kind product); strict {verdict, findings} prompt contract kept; degrades gracefully when codex is absent; opt out with external_reviewer.enabled: false (ADR 0057)"
  - "Added: tested review-loop exit criterion — handoff.review_loop_decision(verdict, iteration, cap, gate_green) → proceed | revise | escalate, the single exit rule shared by develop and product; plus blocks_approve() and canonical constants REVIEW_LOOP_BUDGET / BLOCKING_SEVERITIES / LOOP_DECISIONS; develop/product SKILLs now define a full run's result explicitly (ADR 0057)"
  - "Changed: commit-gate fails open when the gate can't run — a non-zero exit whose output shows a missing lint script / uninstalled linter / missing file (guardrails.gate_unrunnable) is downgraded to an anomaly and allowed, not blocked; real failures still block (ADR 0058)"
  - "Added: diagnostics bundle discloses its audit coverage — diag_bundle.session_coverage compares audit session ids against the repo's transcripts (metadata only) and the README / log-summary show a Coverage line, so a silent audit-logging hole is visible from the bundle (ADR 0058)"
  - "Added: the audit trail records outcome — audit records carry error: true on a clear tool failure (guardrails.tool_errored; additive), and the digest gains errors + by_error_tool with a Failures section so triage can rank tools by failure, not just usage (ADR 0058)"
breaking: []
---

# Release 2026.7.3

Third CalVer release. Two threads ride in it: the **review-cycle upgrade** (ADR 0057 — the external
reviewer becomes a default lens in `develop`/`product`, and the bounded review loop's exit criterion
is now tested code) and a **field-driven diagnostics-fidelity** increment (ADR 0058 — fixes and
disclosures derived from analysing a production diagnostics bundle against its raw transcripts).

## ⚠️ Notable behaviour change — external reviewer on by default

`external_reviewer.enabled` now defaults to **`true`** (was `false`). Where the `codex` CLI is
installed and the setting is left on, `develop` and `product` send the review target (a code diff or
a PRD) to that third-party agent on each review iteration. This is **not** an API break and degrades
to a no-op when `codex` is absent, but it changes default data flow:

- It runs read-only (`codex exec --sandbox read-only`), findings are advisory and verified against
  the source, and the `command` is a bare executable name (no shell).
- **Opt out on secret-bearing repos** with `external_reviewer.enabled: false` (per-repo or user-level
  config; precedence unchanged). See ADR 0057 and the configuration reference.

## Scope

Three commits since `v2026.7.2`:
- `ee35d1f` — external reviewer on by default + tested review-loop exit criterion (ADR 0057).
- `038956e` — field-driven diagnostics fidelity (ADR 0058).
- `496d36f` — make the repo product-agnostic (remove downstream product names from docs/code/tests).

Curated entries live in `CHANGELOG.md` under `[2026.7.3]`. No API-breaking changes; the aggregate is
a feature + behaviour-change release, version per CalVer (the reviewer-default change is flagged
above rather than in the version, per ADR 0055).

## Verification

- Tier-0 `dev/validate.py` OK; `pytest` green (coverage 96.66%); `ruff`/`mypy` clean.
- The commit-gate fix was validated against the real field bundle: all 10 of the production
  diagnostics events (missing `lint` script / `eslint: command not found`) now resolve to fail-open,
  confirmed by running their actual messages through `guardrails.gate_unrunnable`.
- New unit tests: `review_loop_decision` / `blocks_approve` (test_handoff); `gate_unrunnable`,
  `tool_errored`, audit error flag (test_guardrails); commit-gate fail-open vs still-blocks
  (test_guardrail_hooks); digest failure ranking (test_observability); `session_coverage` +
  coverage disclosure (test_diag_bundle).

## Tag

`v2026.7.3` (annotated), to be created on the merged master commit after the PR's rebase merge, per
CONTRIBUTING's "Cutting a release".
