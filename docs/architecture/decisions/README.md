# Architecture Decision Records

Each ADR captures one significant decision: its context, the choice, the alternatives
weighed, and the consequences. ADRs are immutable once accepted; supersede rather than
edit.

| # | Decision | Status |
| --- | --- | --- |
| [0001](0001-claude-code-only-greenfield.md) | Claude Code only, greenfield repo | Accepted |
| [0002](0002-standard-compliance.md) | Conform to the agentskills.io standard | Accepted |
| [0003](0003-eval-driven-pyramid.md) | Eval-driven, contract-first, four-tier pyramid | Accepted |
| [0004](0004-skill-centric-router.md) | Skill-centric with router discipline | Accepted |
| [0005](0005-hybrid-eval-on-skill-creator.md) | Build the eval engine on skill-creator | Accepted |
| [0006](0006-single-file-evals-superset.md) | One `evals.json` superset file | Accepted |
| [0007](0007-python-only-scripts.md) | Python-only, tested scripts | Accepted |
| [0008](0008-evals-first-enforcement.md) | Enforce evals-first via instructions + Tier-0 | Accepted |
| [0009](0009-engine-roles-and-handoff.md) | Engine roles, markdown handoff, bounded review loop | Accepted (agent-eval narrowed by 0011) |
| [0010](0010-handoff-schemas-and-pattern-references.md) | Handoff header schemas + pattern-reference location | Accepted (status/list shape relaxed by 0028) |
| [0011](0011-agent-eval-runner.md) | Dedicated agent eval runner with a pluggable model seam | Accepted |
| [0012](0012-sdlc-spine.md) | Stage 2 SDLC spine: six thin router skills | Superseded by 0013 |
| [0013](0013-spine-workflow-chain.md) | Stage 2 SDLC spine as a chain of phase-workflows | Accepted |
| [0014](0014-software-engineer-base-role.md) | One software-engineer base role + stack skills, not per-stack agents | Accepted |
| [0015](0015-by-stack-detection-and-packs.md) | By-stack: deterministic detection helper + stack reference packs | Accepted |
| [0016](0016-tier1-trigger-runner.md) | Tier-1 trigger runner on live skill descriptions | Accepted (metric refined by 0026) |
| [0017](0017-skill-tier2-runner.md) | Automated skill Tier-2 quality runner | Accepted |
| [0018](0018-l3-knowledge-base.md) | L3 knowledge base: Obsidian vault + recall/capture skill + session-start hook | Accepted |
| [0019](0019-l4-guardrails.md) | L4 guardrails: deterministic hooks (security, test-gate, logging, budgets) | Accepted |
| [0020](0020-tier2-inspection-gradeable-assertions.md) | Tier-2 assertions must be inspection-gradeable; fix gates by fidelity, not lower thresholds | Accepted |
| [0021](0021-stage4-ops-seam-and-eval-tiers.md) | Stage 4: ops adapter seam, incident severity model, fork-orchestrator eval tier | Accepted |
| [0022](0022-stage5-marketing-domain.md) | Stage 5: marketing as one evidence-first router skill (product already covered) | Accepted |
| [0023](0023-stage6-design-onboarding.md) | Stage 6: ux-design (specs not pixels) + repo-onboarding (analyze + seed the vault) | Accepted |
| [0024](0024-stage7-scheduling-observability.md) | Stage 7: scheduling & observability (no daemon — declarative jobs + audit digest) | Accepted (state enriched by 0031) |
| [0025](0025-real-provider-connectors.md) | Real provider connectors: implement the existing seams (Python for CLI/REST, MCP-first for monitoring) | Accepted |
| [0026](0026-tier1-mean-routing-rate.md) | Tier-1 recall/specificity = mean routing-rate (refines ADR 0016): stabler + stricter at the same 0.9 bar | Accepted (remediation in 0029) |
| [0027](0027-deep-review-and-adversarial-pattern.md) | `deep-review` skill + adversarial fan-out review pattern (non-code review; complements `multi-aspect-review`) | Accepted |
| [0028](0028-handoff-contract-relaxation.md) | Relax the handoff contract: open `status` + string-or-object list entries (relaxes 0010); `verdict`/`severity` stay closed | Accepted |
| [0029](0029-tier1-routing-remediation.md) | Tier-1 routing remediation playbook (extends 0026): sharpen descriptions; reword only genuinely-ambiguous prompts, never lower the bar | Accepted |
| [0030](0030-domain-e2e-scenarios.md) | Domain E2E: extend Tier-3 to Stage 4–6 via deterministic chain scenarios (not per-skill); generalize `spine_e2e` into a `Scenario` registry | Accepted (implemented) |
| [0031](0031-scheduling-cadence-persistence.md) | Scheduling cadence persistence: per-job `JobState` (status/runs/failures) + bounded retry of failed jobs (extends 0024) | Accepted |
| [0032](0032-handoff-contract-guard.md) | Handoff-contract guard: skill bodies must document their artifact's required fields | Accepted (design; impl pending) |
| [0033](0033-knowledge-recall-in-spine.md) | Knowledge recall in the spine phases (read the vault to enrich context) | Accepted (design; impl pending) |
| [0034](0034-develop-parallelism.md) | develop parallelism: independent plan tasks across worktrees (tested `plan_batches`) | Accepted (design; impl pending) |
