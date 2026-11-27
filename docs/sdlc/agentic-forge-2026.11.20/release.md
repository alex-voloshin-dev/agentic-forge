---
type: release
feature: agentic-forge-2026.11.20
status: final
version: 2026.11.20
date: 2026-11-27
changelog:
  - "Tier-3 harness: a loop-gated document is read where its phase delivered it (checkout or docs/<slug> worktree, the most recent copy), every handoff checkpoint requires readiness, product-inception is seeded with a bounded FEATURE_REQUEST.md, and Tier-3 sessions get WebSearch/WebFetch; product-inception passes again on Opus 5.5 (ADR 0030 amendment)."
  - "The session-start routing note gains one sentence naming the cheap-delegation pattern by its absolute path in the install; Tier-1b 0.975 pooled before and after (ADR 0113 amendment)."
breaking: []
---
# Release 2026.11.20

Maintainer item M1: Tier-3 `product-inception` failed on 2026.11.17 and 2026.11.18. Field item 6: one routing-note
sentence.

## What changed

- **The Tier-3 harness measures `product-inception` fairly** (ADR 0030, amendment). The investigation found four harness
  causes:
  1. **The checkpoint read a stale copy.** `research`'s retry converged in its docs worktree, but the checkpoint read
     the escalated first attempt in the checkout. Now the six loop-gated document types (research brief, PRD, tech
     design, plan, ux-spec, market brief) are looked for in the checkout and in every `docs/<slug>` worktree. Of
     these copies the most recent is read: a clean tracked file by its last commit, a modified or untracked one by
     its mtime too. That copy must be ready. Every other type is read from the checkout only, as before. The next
     phase's prompt is pointed at the copy that was read.
  2. **ux-spec readiness was not checked,** so an escalated spec passed. Every handoff checkpoint now goes through
     one helper: readiness for loop-gated types, and for the others a written non-`proceed` decision fails.
  3. **The input was unbounded** ("Research the app's domain"). The scenario now seeds a `FEATURE_REQUEST.md` with a
     goal, five acceptance criteria and explicit non-goals. It changes no checkpoint or threshold.
  4. **No web tools,** though research must cite sources by URL. Tier-3 sessions now get `WebSearch` and `WebFetch`,
     so a live run needs network access.

  A re-run with the same `--workspace` also removes a stale docs worktree.
- **The routing note names the cheap-delegation pattern** (ADR 0113, amendment). After the two routing sentences:
  "For large bulk reading (a log, diff or document read only for a few facts) or a mechanical multi-file edit,
  delegate to a low-cost subagent with a short brief and keep the judgement yourself; when and how:
  `<plugin>/patterns/cheap-delegation.md`."
  - The hook fills in the absolute path, so the session can read it as given.
  - It adds about 240 characters at every start and compaction.
  - The same switch turns it off with the rest of the note.

## How it was checked

- **Review.**
  - Harness fix: two reviewer rounds plus one codex follow-up. The reviewer's major was fixed: only loop-gated types
    are searched in worktrees, else a doc phase's stray `review.md` could pass code-review's checkpoint. Its minors
    were fixed too: stale worktree on re-run, recency ranking, `resolve_prompt` paths, the feature request's form,
    and docs. So were codex's two minors: a dirty file's mtime, a relative workspace path. Codex's last minor was
    fixed as well: a restored clean copy counts by its commit, not a fresh mtime. Final codex verdict: approve.
  - Routing note: codex approved. The reviewer's blocker, a stale test that forbade any hook naming the pattern, was
    fixed by pinning the one sentence. Its minors and nits were fixed: the path is in backticks, the README is
    rewrapped, and the length check runs on the built note.
  - Details are in `review-code-1.md`.
- **Tier-3 `product-inception`, live, Opus 5.5: PASS.** Every phase handed off ready. The research brief was read from
  the checkout; the tech design, with 7 ADRs, was read from its docs worktree.
- **Tier-1b, Opus 5.5, 80 prompts over 16 skills:**
  - before (master 798ba5c): 0.975 pooled (78/80);
  - after: 0.975 pooled (78/80), with identical per-skill rates.
- **Tier-0:** `dev/validate.py`, `ruff`, `mypy`, the full pytest suite, and `dev/hook_smoke.py` under Python 3.9.

## Not validated

- **Whether sessions now delegate bulk reading.** No harness counts delegations; the field fleet is asked to report it.
- **The other Tier-3 scenarios.** `spine`, `quality-gate`, `ops-incident` and `market-brief` were not re-run live after
  the checkpoint changes. They pass the dry runner. Their checkpoints now require readiness for loop-gated types
  (`market-brief`) or refuse a written non-`proceed` decision.
- **Tier-2:** not run. No role or skill body changed.

## Known limits

- **Watch item (codex lens).** In several rounds of the failed runs, the external codex lens alone held `changes`.
  Its prompt has no severity rubric and no prior-round context. With a bounded request the loops converged, so the
  lens's gate is not softened.
