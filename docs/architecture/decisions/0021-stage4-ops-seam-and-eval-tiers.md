# 0021 — Stage 4: ops adapter seam, incident severity model, and the fork-orchestrator eval tier

Status: Accepted

## Context

Stage 4 adds five quality/operations phase-workflow skills (`qa-test-strategy`, `security-review`,
`deploy-watch`, `incident-response`, `release`; design in
[quality-ops.md](../quality-ops.md)). Three decisions needed recording: how the ops skills reach
external state without making their evals depend on live infra, how incidents are graded for
severity, and which eval tier each skill takes. The umbrella eval rule is [ADR 0020](0020-tier2-inspection-gradeable-assertions.md)
(assertions must be inspection-gradeable; fix gates by fidelity, never lower the threshold).

## Decision

- **Ops state arrives through a tested adapter seam, never direct provider calls.**
  `lib/agentic_forge/ops.py` defines provider-agnostic `PipelineSource` / `AlertSource` Protocols;
  real connectors (MCP / `gh` / provider APIs) implement them, and `InMemoryPipeline` /
  `InMemoryAlerts` fakes back the tests and the eval fixtures. The assessment — `rollout_health`,
  `triage_alerts`, `deploy_status`, `classify_incident` — is pure and 100% unit-tested. Same
  lib↔skill split as `vault.py`↔`knowledge` and `guardrails.py`↔hooks. Consequence: `deploy-watch`
  and `incident-response` Tier-2 run on recorded snapshots with **no live infra**.
- **Incident severity is a four-level model**, derived not eyeballed:
  `INCIDENT_SEVERITIES = sev1..sev4` in `handoff.py`; `ops.classify_incident(outage, data_loss,
  degraded, workaround)` maps signals → level (sev1 outage/data-loss; sev2 degraded no workaround;
  sev3 degraded with workaround; sev4 cosmetic/latent). Distinct from review-finding `SEVERITIES`
  (`blocker/major/minor/nit`).
- **Eval tier follows the spine convention, not "Tier-2 for everything".** A skill with its **own
  deterministic behavior** (runs a tested lib core) takes skill **Tier-2**, fixture-backed and
  inspection-gradeable: `release`, `deploy-watch`, `incident-response`. A skill that mainly
  **forks a role** takes **Tier-1 + Tier-3** and no skill Tier-2 — `qa-test-strategy` (forks
  `qa-engineer`), `security-review` (forks `security-engineer`) — because testing the orchestrator
  in isolation would just re-test the role, whose agent Tier-2 already gates that quality. This
  matches develop / code-review / plan / architecture / research / product (all Tier-1-only) and
  **corrects** the design doc's initial blanket "Tier-2 each".
- **`release` is deterministic** (`lib/release.py`): conventional-commit classification → semver
  bump (breaking → major, `feat` → minor, else patch; pre-1.0 breaking → minor) → Keep-a-Changelog
  grouping; a thin `commits_since` git seam keeps it testable without a repo.
- **`security-review` reuses the `review` artifact** (verdict + severity-tagged findings) rather
  than a new type — the security lens lives in the skill + the `security-engineer` role.

## Alternatives considered

- **Direct provider calls inside the ops skills** — rejected: untestable and couples Tier-2 to
  live infra. The seam + recorded fixtures keep the gate portable and deterministic.
- **Live infra (or installed agents) in Stage-4 Tier-2** — rejected; the fakes give the same
  signal the read-only grader can verify (ADR 0020).
- **Skill Tier-2 for the fork-orchestrators** — rejected; it re-tests the forked role and
  diverges from the established spine pattern. Tier-1 routing + the role's agent Tier-2 + Tier-3
  is the higher-fidelity gate for an orchestrator.
- **A dedicated `security-review` artifact type** — rejected; `review` already fits (router
  discipline for data shapes).

## Consequences

- New `lib/ops.py` (adapter seam + assessment) and `lib/release.py` (release core), each 100%
  covered; four new handoff types (`test-strategy`, `release`, `incident`, `deploy-status`) +
  `INCIDENT_SEVERITIES`; five Stage-4 skills.
- `deploy-watch` / `incident-response` / `release` carry fixture-backed inspection-gradeable
  Tier-2; `qa-test-strategy` / `security-review` carry Tier-1 + are covered by Tier-3 and their
  roles' Tier-2.
- Real provider connectors (MCP / `gh`) are a follow-on behind the existing Protocols; scheduling
  (headless cadence for deploy-watch digests) stays deferred to Stage 7 (ADR 0019).

## Exit criteria

- All five skills: Tier-0 green; Tier-1 recall/specificity ≥ 0.9; the three own-behavior skills'
  Tier-2 lower bound ≥ 0.8 at n ≥ 5.
- `ops.py` + `release.py` unit-tested (100%); no skill reaches a live provider in tests.
- Docs: this ADR, quality-ops.md, roadmap/overview, CHANGELOG per step.
