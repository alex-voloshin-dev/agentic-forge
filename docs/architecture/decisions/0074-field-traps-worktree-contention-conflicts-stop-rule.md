# 0074 — Field traps: worktree hazards, build contention, semantic PR conflicts, and a stop rule

**Status:** Accepted (implemented)
**Date:** 2026-07-26
**Extends:** 0033/0034 (worktree + parallel worktree), the review lens catalog,
`engineering-standards`.

## Context

Four P1 findings from the 2026-07-26 field report (**AF-07**, **AF-08**, **AF-09**, **AF-10**).
None is a plugin bug — each is a hazard the plugin *knew nothing about* and therefore never warned
an agent to avoid. All four were hit in production work; two of the worktree traps silently
corrupt the main checkout, and the AF-09 conflict reached production.

They are grouped into one ADR because they share a shape: **an isolation or verification mechanism
the plugin presents as sufficient, which is not.**

## Decision

### 1. Worktree traps (`patterns/worktree.md`) — AF-07

A worktree is not automatically safe, in four documented ways:

- **A write through the main checkout's path lands on the base branch.** Tools accept `/repo/foo.ts`
  while a worktree is active; the edit silently leaves the branch and never appears in the PR.
  *Re-derive every write path from the worktree root; never reuse a path captured before the
  worktree existed.*
- **`git diff <base>` in a stale worktree shows phantom deletions** — everything the base gained
  since the cut is rendered as deletions in your branch, which reads as massive off-scope removal.
  *Diff against the merge-base.*
- **`git worktree remove --force` follows a `node_modules` symlink and empties its target** — the
  main checkout's real dependency tree. *Remove the symlink first; never `--force` a worktree with
  symlinks pointing outside itself.*
- **Code generators must run in the package's native checkout.** Through a symlinked dependency
  tree a generator resolves different packages and emitted ESM imports without the required `.js`
  extension, breaking the build.

### 2. Contention is not conflict (`patterns/worktree-parallel.md`) — AF-08

A worktree isolates the *source tree*, not what the build and tests reach for.

- **Serialize agents that compile the same module** — concurrent builds in one module directory
  clobber the shared build output, surfacing as nondeterministic compile or missing-class errors.
  Fan out across modules, not within one.
- **Suspect contention before regression** — concurrent container-backed suites produce startup
  failures indistinguishable from real regressions. *Re-run in isolation before reporting a
  regression or bisecting.* The rule generalises to any shared singleton: a fixed port, a named
  volume, a shared database.

### 3. No textual conflict ≠ no semantic conflict — AF-09

Added as a review lens (`deep-review/references/lenses.md`) and a `code-review` aspect. When a diff
adds or changes a **claim / lock / lease / dedup guard / status transition**, search the other
in-flight branches and open PRs for the *same state transition* — not the same files.

The field case: one PR pre-claimed `QUEUED → PROCESSING` in the scheduler, another added an atomic
`UPDATE … WHERE status = QUEUED` in the worker. Different files, clean merge, both CI runs green
because each PR's tests exercised only its own entry point. Together they halted all processing —
the worker's claim matched zero rows and skipped every item as a duplicate. Found in production.

Two secondary rules come with it: prefer claiming **atomically at the point of work** (an upstream
pre-claim opens a window where a row looks claimed but no worker owns it, which recovery sweeps
misclassify), and note for the tests lens that **cross-entry-point** coverage is what would have
caught it.

### 4. A stop rule for speculative fixing (`engineering-standards`, `develop`) — AF-10

A feature returned no data for *every* input since launch. Two input-specific theories were
authored, reviewed, merged and deployed, both with green unit tests; neither worked. The cause was
serialization — the upstream API returned one field as `"0.03"` while its siblings were numbers,
and the extractor accepted only numerics. One diagnostic run (raising existing DEBUG logs to INFO)
showed HTTP 200 with a populated body and `hasData=false`, which is unambiguously a parse bug.

- **Systemic or per-input**: a defect that fails for everyone, always, is parsing, serialization or
  one wiring mistake — not an edge case.
- **Two-strike rule**: after ~2 failed hypotheses, stop shipping fixes and obtain ground truth.
- **Read the signal**: an empty result on a populated HTTP 200 is a parsing bug; external APIs are
  not type-uniform.
- **Verify against the real failure, not the unit tests** — both wrong fixes had green tests.

## Consequences

- Two silent corruption modes of the main checkout are now warned about at the point of use, where
  neither had any coverage.
- A parallel run's flaky failure has a documented first hypothesis (contention), which is the
  cheaper one to test.
- The review gate gains the only class of defect it structurally could not see: one that exists
  *between* two individually-correct changes.
- `develop`'s QA loop stops rewarding a third guess. Expect diagnostic-only changes to appear in
  runs that previously produced another speculative fix.
- **All four are instruction-level**, like ADR 0073 — model-followed rules, unenforceable by hooks.
  The worktree traps in particular would benefit from a real guard (a hook that rejects a write to
  the main checkout while a worktree is active); that is noted as future work, not built.
