# 0035 — ultra-review hardening: gate integrity, deny-list scope, redaction, doc honesty

Status: Accepted — **implemented** (see the [Unreleased] CHANGELOG entry).

## Context

A multi-lens adversarial review of the whole session (deterministic cores, eval/gate integrity,
security/safety, tests/coverage, docs/ADRs, cross-cutting architecture, skills/patterns) — each
finding verified against source — surfaced defects that the always-green Tier-0 gate could not
self-detect, because they live exactly where line/branch coverage is blind: the gate's own
pass/fail policy, the security deny-lists, and constitution-vs-reality drift. This ADR records the
**decisions** behind the fixes (the mechanical bug fixes are in the CHANGELOG; the policy choices
are here).

## Decision

1. **A declared eval tier with no effective threshold FAILS; it is never a vacuous PASS.**
   `gate.tier2_quality` now fails when `min_pass_rate` is absent, `gate.all_passed([])` returns
   False (no data ≠ pass, mirroring `tier1_runner`), and the contract **schema** `require`s the
   threshold sub-fields (`min_pass_rate`; `recall`+`specificity`) and forbids unknown `thresholds`
   keys. Rationale: "numeric thresholds are the definition of done" (CLAUDE.md principle 3) must be
   enforced structurally, so a malformed/empty contract cannot score PASS with every assertion
   failing. All 33 current contracts already comply.

2. **The eval-decision code in `dev/` is coverage-gated like the library.** Coverage `source`
   includes `dev`, with `fail_under = 80` in `pyproject` (so local `pytest --cov` and CI agree) and
   CI switched to config-driven `--cov`. The runners' aggregation/exit-code path is exercised by
   stub-transport tests. Rationale: the runners decide ship/no-ship; leaving them unmeasured
   contradicted principle 5.

3. **The security hook is a per-segment accident-guard, and that scope is documented, not implied.**
   Dangerous-command checks evaluate **per shell segment** (so an unrelated clause cannot poison the
   line, and a danger must co-occur in one command); the deny-list and secret redaction were
   broadened to the obvious modern shapes (force-push refspec destinations, non-bash pipe-to-shell,
   permissive recursive `chmod`, and `sk-ant-…`/`gh*_`/JWT/URL-credential secrets). `guardrails.md`
   now states the accepted limits (command-substitution downloads, bare `git push --force`, the
   test-gate running repo-local code from `cwd`). Rationale: redaction protects `audit.jsonl` in
   Anthropic's own tooling — the highest-value leak — and an honest scope prevents the deny-list
   being mistaken for an adversarial sandbox.

4. **The constitution describes the delegation mechanism that actually ships.** CLAUDE.md
   principle 1 said agents are delegated via `context: fork` + `agent` frontmatter, which **no skill
   uses**; it now documents the real convention — the `Task` tool in `allowed-tools` referencing the
   role by name. Likewise principle 4 + meta-core mark Tier-2 token/time-overhead and with/without
   A/B as **scaffolded but not yet wired** (pass-rate is the live gate). Rationale: the rulebook and
   the docs must match the code, or they mislead every future contributor.

## Alternatives considered

- **Lower or relax a threshold to make a flaky check pass:** rejected on sight — the standing rule
  is improve the component / make the eval fairer, never lower the 0.9/0.8 bar (ADR 0020/0029). No
  threshold value changed here; only vacuous-pass *paths* were closed.
- **Adopt the `context: fork`/`agent` frontmatter to match principle 1 (instead of fixing the doc):**
  rejected — the shipped `Task`-tool convention works and is tested end-to-end; rewriting 11 skills'
  delegation to an unused primitive is churn with no behavioural gain. Make the doc honest instead.
- **Harden the security deny-list into a real sandbox:** rejected — it is deliberately conservative
  (false blocks cause friction). We closed the *accidental*-footgun gaps and **documented** the
  adversarial limits rather than overpromising a boundary the design doesn't provide.
- **Delete the dead Tier-2 overhead/A-B scaffolding:** deferred, not done — it is harness-ready for
  when the runners capture timing; the honest fix now is to document it as dormant, not remove it.

## Consequences

- A new or edited contract that omits its thresholds is now rejected at Tier 0 (schema) and would
  fail the gate (defence in depth) — no silent vacuous pass.
- `dev/` regressions in the ship/no-ship logic are caught by coverage; the library is at 100%,
  aggregate 98%.
- The security hook blocks more real hazards and fewer false positives, with its true scope written
  down; secret redaction covers the common token shapes (not exhaustive — `audit.jsonl` stays
  sensitive).
- CLAUDE.md, meta-core, and the pattern/skill docs now match the implementation. Cosmetic cleanups
  (`__all__` backfill, de-duplicating `summary_line`/`all_passed`/`DEFAULT_RUNS`, removing dead
  `Change.raw` / `classify_incident(cosmetic=)` / the `spine_e2e` back-compat trio) and deeper
  test-quality (mocking the judge transport; de-tautologising the develop /
  `expected_release_version` checkpoints) were all completed in follow-up commits (see the
  CHANGELOG) — nothing from the review remains outstanding.
