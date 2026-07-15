# Stage 4 — Quality & operations domains

Five phase-workflow skills that extend the SDLC spine past `develop` / `code-review` into
**quality** (`qa-test-strategy`, `security-review`) and **operations** (`deploy-watch`,
`incident-response`, `release`). Like the existing spine skills they compose the engine roles and
patterns rather than doing the work inline, and each emits a typed [handoff](../../plugin/patterns/handoff.md)
artifact. Built contract-first → evals-first → implementation, with **inspection-gradeable,
fixture-backed Tier-2 from the start** (ADR 0020). Roadmap: Stage 4.

## Skills

| Skill | Purpose | Forks | Handoff artifact | Trigger boundary |
| --- | --- | --- | --- | --- |
| `qa-test-strategy` | Plan *what to test* for a change/feature: risk areas, test levels, prioritized cases, coverage targets, data/fixtures needed | `qa-engineer` (analysis mode) | `test-strategy` | Strategy, **not** writing tests (`develop`'s QA step) or reviewing code (`code-review`) |
| `security-review` | Dedicated deep security pass over a component/design/change: threat surface, authz, secrets, deps, input handling | `security-engineer` | `review` (reused; security lens) | Whole-target audit, **not** the per-diff security aspect inside `code-review`, **not** fixing (`develop`) |
| `deploy-watch` | Read CI/CD pipeline state + alerts — or a k8s cluster/namespace (nodes, pods, events; `references/k8s-health.md`) — summarize rollout health, flag regressions, recommend action | — (deterministic `ops` core) | `deploy-status` | Read/assess a deploy, **not** incident handling (`incident-response`) or cutting a release (`release`) |
| `incident-response` | Classify severity, assemble timeline, coordinate mitigation, draft a postmortem | `architect`/`security-engineer` as the cause needs | `incident` | Active incident/postmortem, **not** routine deploy monitoring (`deploy-watch`) |
| `release` | Cut a release: derive the next version (semver, or CalVer per ADR 0055), assemble the changelog from merged PRs/commits since the last tag, produce release notes | — (deterministic `release` core) | `release` | Assemble/tag a release, **not** the per-PR `CHANGELOG` discipline during dev |
| `pr-watch` | Off-listing manual `/pr-watch`: babysit one PR/CI run — paced polls, transition-only reports, opt-in bounded fix loop over the `agentic_forge.pr_watch` lib | `software-engineer` for non-trivial fixes | — (interactive reports) | Interactive single-PR watching, **not** the scheduled multi-repo watcher (`dev/pr_watch.py`) or rollout health (`deploy-watch`) |

## Resolved design questions (from the roadmap)

- **Ops integration = a tested adapter seam, not direct calls.** `deploy-watch` and
  `incident-response` read external state (pipeline status, alerts/monitoring). That state comes
  through a provider-agnostic seam in `lib/agentic_forge/ops.py`: small interfaces
  (`PipelineSource`, `AlertSource`) with real connectors (MCP / `gh` CLI / provider APIs) behind
  them and an **in-memory fake** for tests. The decision logic — rollout-health summary, anomaly
  flagging, incident-severity classification, digest rendering — is deterministic and
  unit-tested; the skills call it. This is the same lib↔skill split as `vault.py`↔`knowledge` and
  `guardrails.py`↔hooks, and it keeps Stage-4 **Tier-2 runnable with no live infra** (fixtures are
  recorded pipeline/alert JSON fed through the fake).
- **Incident severity model.** A four-level enum on the `incident` artifact —
  `sev1` (critical: outage / data loss), `sev2` (major: degraded, no workaround), `sev3` (minor:
  degraded, workaround exists), `sev4` (low: cosmetic / latent). Classification criteria live in
  `ops.py` (tested) so the level is derived, not guessed. (Distinct from finding `SEVERITIES`
  `blocker/major/minor/nit`, which stay for review findings.)
- **Release conventions.** Semver + [Keep a Changelog](https://keepachangelog.com/) sections
  (Added / Changed / Fixed / Removed) — consistent with this repo's own `CHANGELOG.md`. `release`
  reads merged PRs/commits since the last tag (`git` + `gh`), groups them, and proposes the bump
  (breaking → major, feat → minor, fix → patch).
- **Triggering.** Event- or CI-invoked for now; **headless scheduling stays deferred to Stage 7**
  (ADR 0019), so deploy-watch/incident-response are invoked on demand, not on a cron.

## New handoff artifact types (`handoff.py` `SCHEMAS`, contract-first)

- `test-strategy` — feature schema + `scope`, `risks`, `test_levels` (non-empty), `cases`.
- `release` — feature schema + `version`, `changelog` (non-empty; Keep-a-Changelog groups),
  `breaking` (list).
- `incident` — `severity` (sev1–4), `status`, `impact`, `timeline` (non-empty), `remediation`,
  `action_items`.
- `deploy-status` — `environment`, `pipeline` state, `deploys` (recent), `alerts`, `action`.
- `security-review` **reuses `review`** (target/iteration/verdict/findings-with-severity) — no new
  type, to avoid sprawl; the security lens is in the skill + `security-engineer` role, not a new
  schema.

## Eval approach (ADR 0020 from the start)

The eval tier follows the **established spine convention** (confirmed across develop / code-review /
plan / architecture / research / product): a skill with its **own deterministic behavior** carries
skill **Tier-2**; a skill that mainly **forks a role** is **Tier-1-only** and validated end-to-end
by Tier-3 plus the forked role's agent Tier-2 (no skill Tier-2 — testing the orchestrator in
isolation would just re-test the role).

- **Tier-1** triggers for **all five** (`should_trigger` / `should_not_trigger`, recall &
  specificity ≥ 0.9), with the boundaries above as negatives (e.g. `release` must *not* fire on
  "watch the deploy"; `security-review` must *not* fire on a routine code review).
- **Tier-2** (fixture-backed, **inspection-gradeable** — the read-only grader reads the output +
  files, never runs infra) for the **own-behavior** skills, which run their tested lib core:
  - `release`: a fixture commit list → correct semver bump + Keep-a-Changelog grouping (done).
  - `deploy-watch`: fixture pipeline/alert JSON through the **fake `ops` adapter** → correct
    health, triage, and recommended action; a schema-valid `deploy-status` artifact.
  - `incident-response`: a fixture incident scenario → correct `sev1`–`sev4` classification and a
    schema-valid `incident` artifact (severity, impact, timeline, remediation).
- **Tier-1 + Tier-3 only** for the **fork-orchestrators** (consistent with develop/code-review):
  - `qa-test-strategy` forks `qa-engineer`; `security-review` forks `security-engineer`. Their
    quality is the forked role's (already gated by agent Tier-2) plus the end-to-end Tier-3
    scenario; a planted-vulnerability fixture lives with the `security-engineer` role eval.

## Alternatives considered

- **A new `security-review` artifact type** — rejected; `review` already carries
  verdict + severity-tagged findings. Reuse keeps the schema set small (router discipline for
  data shapes).
- **Direct provider calls in the ops skills** — rejected; untestable and couples Tier-2 to live
  infra. The adapter seam + recorded fixtures keep the gate portable.
- **Live infra in Stage-4 Tier-2** — rejected for the same reason; fakes + recorded state give a
  deterministic, ADR-0020-consistent gate.
- **Folding `security-review` into `code-review`** — rejected; `code-review`'s security aspect is
  per-diff and inline, whereas `security-review` is a deeper whole-target audit (threat surface,
  deps, secrets) that warrants its own workflow + handoff.

## Exit criteria

- Each skill: Tier-0 green; Tier-1 recall/specificity ≥ 0.9; Tier-2 lower bound ≥ 0.8 over n ≥ 5,
  fixture-backed and inspection-gradeable.
- `ops.py` + `release` core: unit-tested (aim 100%), the external seam covered by a fake; no skill
  reaches a live provider in tests.
- New handoff schemas added to `handoff.py` **with tests**, validated by Tier-0.
- Docs: this design, an ADR for the ops adapter seam + severity model, roadmap/overview updated,
  CHANGELOG per step.
