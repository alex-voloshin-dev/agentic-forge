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
| [0032](0032-handoff-contract-guard.md) | Handoff-contract guard: skill bodies must document their artifact's required fields | Accepted (implemented) |
| [0033](0033-knowledge-recall-in-spine.md) | Knowledge recall in the spine phases (read the vault to enrich context) | Accepted (implemented) |
| [0034](0034-develop-parallelism.md) | develop parallelism: independent plan tasks across worktrees (tested `plan_batches`) | Accepted (implemented) |
| [0035](0035-ultra-review-hardening.md) | Ultra-review hardening: fail vacuous eval tiers, gate `dev/` coverage, per-segment deny-list + broader redaction, constitution matches code | Accepted (implemented) |
| [0036](0036-tier2-ab-overhead-wiring.md) | Tier-2 A/B + overhead wiring: `--baseline` with/without pass-rate lift + wall-clock overhead gates | Accepted (implemented) |
| [0037](0037-review-passes-for-artifact-writers.md) | Review/skeptic passes for artifact-writer workflows (product, marketing, ux-design); loop-reference symmetry | Accepted (implemented) |
| [0038](0038-token-overhead-wiring.md) | Token-overhead gate wired into the Tier-2 A/B (`max_overhead_tokens`) (extends 0036) | Accepted (implemented) |
| [0039](0039-diagnostics-channel.md) | Opt-in self-diagnostics channel: errors/denials/anomalies → `diagnostics.jsonl` + digest | Accepted (implemented) |
| [0040](0040-review-loop-non-convergence-scan.md) | Review-loop non-convergence scan: detect loops that never converge and escalate | Accepted (implemented) |
| [0041](0041-plugin-settings.md) | Plugin settings: configurable behavior via `settings` + `config.schema.json` | Accepted (implemented) |
| [0042](0042-external-reviewer.md) | External reviewer seam (codex) for an independent review pass | Accepted (implemented; default + wiring updated by 0057) |
| [0043](0043-multi-model-tiers.md) | Multi-model tiers: per-role model policy (`models.py`) | Accepted (implemented; routing wired by 0046) |
| [0044](0044-pr-watcher.md) | PR watcher: monitor a GitHub PR + bounded auto-fix loop | Accepted (implemented) |
| [0045](0045-pr-watcher-1b.md) | PR watcher 1b: scheduled job over repos + mechanical conflict resolution (extends 0044) | Accepted (implemented) |
| [0046](0046-runtime-model-routing.md) | Runtime model routing: the validated tier reaches live `Task` delegation (wires 0043) | Accepted (implemented) |
| [0047](0047-version-over-version-ab.md) | Version-over-version A/B: stored benchmark history + regression gate (`max_regression`) | Accepted (implemented) |
| [0048](0048-ralph-loop.md) | Ralph loop: bounded autonomous iteration (engine core `lib/ralph.py` + driver `dev/ralph.py`) | Accepted (implemented) |
| [0049](0049-user-level-config.md) | User-level (cross-project) config layer `~/.agentic-forge/config.json`; precedence defaults < user < repo < env (extends 0041) | Accepted (implemented) |
| [0050](0050-hook-import-safety.md) | Guardrail hooks import on a stdlib-only, version-robust path (lazy jsonschema/PyYAML, `timezone.utc`); upholds 0019 | Accepted (implemented) |
| [0051](0051-narrow-network-download-denylist.md) | Narrow the "network download into a shell" deny-list: exempt loopback, require a bare interpreter (stdin-as-program), anchor curl/wget to command position (refines 0019) | Accepted (implemented) |
| [0052](0052-diagnostics-bundle-and-audit-fidelity.md) | Analyzable production diagnostics: audit records stay valid JSON (per-field truncation) + a one-command redacted bundle packager (`diag_bundle.py`) | Accepted (implemented) |
| [0053](0053-diagnostics-bundle-skill.md) | `diagnostics-bundle` skill (off-listing, manual): windowed (last N days, default 7) bundle to `~/Downloads` with consistent naming; timestamps the audit trail (extends 0052) | Accepted (implemented) |
| [0054](0054-command-position-denylist.md) | Deny-list rules fire on the command word of a quote-aware, shlex-tokenized segment — quoted mentions are data; `sh -c`/`$(…)` payloads recurse (completes 0051) | Accepted (implemented) |
| [0055](0055-calver-versioning.md) | CalVer plugin versioning `<year>.<month>.<inc>` (semver-compatible ordering, monthly counter; breaking changes live in the changelog) — first CalVer cut is 2026.7.1 | Accepted (implemented) |
| [0056](0056-external-skill-adoption.md) | Adopt the maintainer's skill-library content as references (GEO/SEO audit, offer design, social content gates, PM frameworks, design handoff, bug reports, reader-testing lens) — references-first, no new on-listing skills | Accepted (implemented) |
| [0057](0057-external-reviewer-on-by-default.md) | External reviewer on by default + auto-wired as an extra lens into `develop` (code) and `product` (PRD) review loops; strict prompt contract kept (updates 0042) | Accepted (implemented) |
| [0058](0058-field-diagnostics-fidelity.md) | Field-driven diagnostics fidelity (from a production bundle): commit-gate fails open when the gate can't run; bundle discloses audit coverage; audit records tool-error flag; digest ranks failing tools | Accepted (implemented; unrunnable detection tightened by 0059) |
| [0059](0059-commit-gate-unrunnable-precision.md) | Commit-gate unrunnable-detection precision (0058 hotfix): drop over-broad `not found`/`no such file` substrings, catch the shell's own not-found by exit code 127/126, separate stdout/stderr, best-effort transcript read tolerates bad UTF-8 | Accepted (implemented) |
| [0060](0060-skeptic-loop-architecture-plan.md) | Mandatory bounded skeptic loop + the external-reviewer lens in `architecture` (`--kind technical`) and `plan` (`--kind plan`); `plan`'s DAG proved by `plan_batches`; `Bash` added to those skills' + `product`'s `allowed-tools` (extends 0057, closes an 0037 gap) | Accepted (implemented; completed by 0061) |
| [0061](0061-skeptic-loop-research-ux.md) | The same loop + lens reach `research` (new skeptic pass) and `ux-design` (exit criterion added); two new `external_review.KINDS` (`research`, `ux`) so neither falls back to the code criteria; `Bash` added to both (completes 0060 / 0037) | Accepted (implemented; `KINDS` invariant refined by 0062) |
| [0062](0062-skeptic-loop-marketing.md) | `marketing`'s claims pass gains the shared `review_loop_decision` exit (conditional `gate_green`: schema for a typed handoff, the evidence discipline otherwise), the external lens, and an `Output` section; `KINDS` invariant refined to one kind per review-criteria set (completes the 0060/0061 sweep) | Accepted (implemented) |
| [0063](0063-autonomous-pr-watch.md) | Autonomous PR watch: pure `merge_readiness` gate + opt-in `auto_merge` (**reverses 0044/0045's never-merge invariant**; never-force-push stands), never merge in the pass that pushed, comment triage through the develop review loop, PR-created hook | Accepted (implemented) |
| [0064](0064-tier1-measurement-integrity.md) | Tier-1 measurement integrity: an off-format router reply is `INVALID`, not a routing decision — excluded from the denominator, an all-invalid prompt is `unmeasured` and fails the gate, discarded calls always reported; router gets `--system-prompt` (replace) instead of append (corrects 0016/0026's contract) | Accepted (implemented) |
| [0065](0065-merge-outcome-is-observed.md) | The merge outcome is read from the PR (`merged_argv` / `parse_merged` + a `confirm_merged` seam), not inferred from `gh pr merge`'s exit status — it merges remotely then does local work that can fail on its own; without the seam a failure still propagates (hardens 0063) | Accepted (implemented) |
| [0066](0066-frontmatter-colon-quoting.md) | Every artifact-writing skill must demand valid YAML frontmatter (quote colon-bearing values), each with its own likely offender — found by the first LIVE Tier-3 run; the guidance existed only in `ux-design` and one E2E prompt, so five skills lacked it | Accepted (implemented) |
| [0067](0067-deep-review-remediation.md) | Deep-review remediation: `run_watch` recomputes the merge gate + requires `auto_merge` and the CLI wires it (the rails had NO production caller); gate blocks on CHANGES_REQUESTED / truncated threads / closed PR; watcher settings resolved before `gh pr checkout`; `escalate` sets a not-ready status that consumers and Tier-3 check; Tier-1 parser guards non-Latin prose, negation, acting and thin samples; hook handles newlines and reads stdout only; review artifacts persisted; shape test added | Accepted (implemented) |
