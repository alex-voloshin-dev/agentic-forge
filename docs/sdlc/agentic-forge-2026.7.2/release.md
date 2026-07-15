---
type: release
feature: agentic-forge-2026.7.2
status: final
version: 2026.7.2
date: 2026-07-15
changelog:
  - "Added: pr-watch skill — off-listing interactive PR/CI babysitting over the agentic_forge.pr_watch lib (paced polls, transition-only reports, opt-in bounded fix loop; never merge / never force-push) — Tier-2 PASS 0.986/0.954 (n=5)"
  - "Added: deploy-watch Kubernetes cluster-health path (references/k8s-health.md, observation→verdict mapping, headless recipe) — Tier-1 PASS 0.971/1.000, Tier-2 PASS 1.000 (n=5)"
  - "Added: deep-review canonical Workflow template (fixed finding/verdict schemas, per-lens retry-once, loss disclosure) and a reader-testing docs lens"
  - "Added: skill-library adoption (ADR 0056) — marketing gains geo-content / offer-design references plus an extended content reference with the anti-AI writing gate; product gains prioritization frameworks; ux-design gains the design-handoff template; qa-test-strategy gains bug-report/exploratory guidance — Tier-1 marketing 0.911/1.000, product 1.000/0.960; Tier-2 marketing 0.962, ux-design 1.000"
  - "Changed: observability hygiene — size-bounded atomic audit-log rotation at session start; worktree-aware log placement (main_repo_root) symmetric on the read side; settings-slice filtered to agentic-forge entries incl. the hosting marketplace"
  - "Added: CONTRIBUTING 'Cutting a release' guide (PR-only master ruleset, tag-after-rebase-merge)"
breaking: []
---

# Release 2026.7.2

Second CalVer release. Two increments ride in it: the **field-driven plan** from the July-2026
production diagnostics (pr-watch, deploy-watch k8s, deep-review template, observability hygiene)
and the **skill-library adoption** (ADR 0056), plus the CONTRIBUTING release-flow guide.

## Scope

Three commits since `v2026.7.1`: `873c8b5` (CONTRIBUTING guide), `4ed4fea` (field-driven
increments), `af23077` (ADR 0056 adoption). Curated entries live in `CHANGELOG.md` under
`[2026.7.2]`. No breaking changes; the semantic level of the aggregate is a feature release
(new skill + new references), version per CalVer.

## Verification

- Tier-0 `dev/validate.py` OK; `pytest` green (coverage 96.6%); `ruff`/`mypy` clean.
- Live eval gates (claude-opus-4-8, n=5): pr-watch Tier-2 0.986/0.954 (re-run on the
  review-amended contract); deploy-watch Tier-1 0.971/1.000 + Tier-2 1.000; marketing Tier-1
  0.911/1.000 + Tier-2 0.962; product Tier-1 1.000/0.960; ux-design Tier-2 1.000.
- Pre-release deep review: four adversarial lenses over the whole working tree; all verified
  findings fixed before the commits (read-side log normalization, rotation guards + atomic
  replace, stale-gitdir guard, eval no-live-sleep guards, parse_pr-compatible fixtures, doc
  corrections incl. ADR 0056 accuracy and the eval-runbook lessons).

## Tag

`v2026.7.2` (annotated), created on the merged master commit after the PR's rebase merge, per
CONTRIBUTING's "Cutting a release".
