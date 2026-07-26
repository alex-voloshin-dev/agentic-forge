---
name: develop
description: Implement a planned change — set up a git worktree, write the code and tests for the current step (via the software-engineer role), gate it with a multi-aspect review, loop back on changes, then harden tests via the qa-engineer role. Use to implement, build, or write the code for a plan or feature step. Not for designing the approach (architecture), breaking work into tasks (plan), or reviewing existing code only (code-review).
allowed-tools: Read, Grep, Glob, Bash, Task, Write, Edit
---

# Develop (phase workflow)

The implementation phase of the SDLC spine — the flagship workflow. It turns a plan step into
working, reviewed, tested code in an isolated git worktree, then hands off. It composes the
engine roles and patterns rather than doing the work inline, and **owns the worktree
lifecycle**.

## When to use

When a `plan.md` and/or `tech-design.md` exist and the task is to *build* the change. Not for
designing (`architecture`), task breakdown (`plan`), or reviewing already-written code
(`code-review`).

## Process

> **Recall first** — pull the project's relevant prior decisions from the knowledge vault (see
> [knowledge-recall](../../patterns/knowledge-recall.md)); factor them in, and skip if the vault is empty.

1. **Read inputs; fix the slug; detect the stack.** Load `plan.md` if present
   (`handoff.load_artifact(..., expected_type="plan")`; **refuse to build from it unless `handoff.is_handoff_ready(header)`**) and/or `tech-design.md`; derive
   `<feature-slug>` from the artifact's `feature` header. Pick the current step and the
   components it touches. Detect the target repo's stack —
   `stacks.primary(<repo>)` (`stacks.detect` for monorepos) — and note the profile (pack +
   toolchain); its commands are fallbacks, so **prefer the repo's own declared commands**.
2. **Batch the work; set up isolation.** Compute the plan's dependency levels with
   `planning.plan_batches(tasks)` — each level is a set of independent tasks. Process levels **in
   order**; within a level, **fan out one git worktree per task** and run their implementations
   **concurrently** (see [worktree-parallel.md](../../patterns/worktree-parallel.md) +
   [worktree.md](../../patterns/worktree.md)); a one-task level (or a plan with no parallelism) is
   the single-worktree case. `git init` + an initial commit first if the target is not yet a git repo.
3. **Implement (per task, concurrently).** For each task in the level, spawn a
   [`software-engineer`](../../agents/software-engineer.md) (via `Task`, **not the `fork` subagent
   type** — [subagent-type rule](../../patterns/fan-out-fan-in.md#choosing-the-subagent-type)) into **its own worktree**;
   each re-derives the stack profile there (the same `stacks` helper, so the result matches step 1)
   and loads `engineering-standards` + the detected `<stack>-patterns` pack (e.g. `python-patterns`;
   if the profile has no pack, the standards + the profile's toolchain), writes the code and its
   tests in its worktree, and reports files/tests/assumptions. Keep each change scoped to its task.
4. **Integrate, then review.** When a level's worktrees finish, **integrate** them — merge each
   into the base branch in a deterministic order (e.g. by task id), resolving conflicts
   ([worktree-parallel.md](../../patterns/worktree-parallel.md)); if a conflict can't be resolved
   mechanically, route it to a `software-engineer` (under the N = 3 budget) or surface it and stop —
   integration has the same stop discipline as review/QA. Then produce the integrated diff
   — `git -C <repo> add -A && git -C <repo> diff --staged` (staging so new files are included) — and
   pass that diff text to the [multi-aspect review](../../patterns/multi-aspect-review.md) (the
   `code-review` engine: `reviewer` + `security-engineer` + the stack's lint/type tools from the
   profile/repo). The LLM reviewers receive the diff as input and need no git access; the lint/type
   aspect runs the stack tools on the integrated files. **External reviewer lens (on by default,
   ADR 0057):** when `external_reviewer.enabled` (settings), also run the external reviewer over the
   same diff — call `agentic_forge`'s `external_review.review(diff, "code", command=<cfg>)` from
   `${CLAUDE_PLUGIN_ROOT}/lib` (the same way this workflow already calls `handoff` / `stacks` /
   `planning`; the repo-side CLI `${CLAUDE_PLUGIN_ROOT}/bin/external_review.py --kind code` is the equivalent entry point
   when running in this repo). codex reviews it **read-only** as an independent-model lens and its
   `findings` fold into the aggregation at their own severity. It
   **degrades gracefully** — absent/disabled/unparseable codex is *skipped, not a failure* — and its
   findings are **advisory** (prompt-injectable): verify each against the source before acting, like
   any finding. Aggregate all aspects (internal + external) to one approve/changes verdict. **Advance to the next dependency level only after this one integrates,
   is approved, and its QA is green.**
5. **Loop back (bounded) — the exit criterion.** **Persist each round** — one `review-<artifact>-<iteration>.md` per round under `docs/sdlc/<feature-slug>/`, aggregating **both** lenses; on `proceed` keep only the final round, on `escalate` keep them all (naming + lifecycle: [review-loop.md](../../patterns/review-loop.md)). Compute the next action with the shared, tested
   rule `handoff.review_loop_decision(verdict, iteration, cap=3, gate_green=<suite green + QA
   passed>)` (see [patterns/review-loop.md](../../patterns/review-loop.md)):
   - **`revise`** — verdict `changes` and iteration < 3: return the findings to step 3, fix
     worst-first, re-integrate, re-review.
   - **`escalate`** — verdict still `changes` at iteration 3 (budget exhausted): **do not proceed
     or merge** — surface the unresolved findings to the user and stop.
   - **`proceed`** — verdict `approve` **and** QA is green (step 6): the loop exits successfully.
   Only `proceed` lets develop advance a level and, at the last level, hand off.
6. **QA.** Delegate to the [`qa-engineer`](../../agents/qa-engineer.md) role against the
   **integrated base** (where the level now lives; for a single-task level that is its worktree):
   strengthen the suite (existing + new unit + end-to-end) and run it. A
   surfaced defect re-enters at step 3 → step 4 (re-review) → step 6, under the **same N = 3
   budget**; if still failing at the budget, surface the defect and stop. Never weaken a test
   to pass. **Two-strike rule** (`engineering-standards`): after ~2 failed hypotheses about a
   defect, stop shipping fixes and get ground truth — a diagnostic run beats a third guess, and a
   defect that fails for *every* input is parsing/serialization/wiring, not an edge case.
7. **Hand off and clean up.** On `approve` + green suite: the integrated base holds the reviewed,
   tested change, ready to merge. Report the change summary. **develop owns the worktree
   lifecycle — remove *each* worktree (`git worktree remove`) once its change is merged or
   abandoned, even on failure** (worktree.md).

## Output

**A full develop run produces fully-ready code for the feature: every dependency level of the plan
implemented, reviewed to `approve`, and tested green** — the integrated base is merge-ready. Plus a
structured change summary (files, tests, assumptions) and the final review verdict. The main
checkout is never modified. (develop's gate is the review **verdict** + QA that drives the loop; the
canonical `review.md` handoff artifact belongs to the dedicated `code-review` phase, though the
review engine may emit one into the worktree.) A run that cannot reach this — the loop `escalate`s
(review still `changes` at N = 3) or QA can't go green — stops and surfaces the blockers; it does
**not** hand off partial code.

## Definition of done

- **Every** dependency level of the plan is implemented (not just one step), each scoped, with tests
  added and the whole suite green.
- The multi-aspect review (internal aspects + the external-reviewer lens when enabled) exits on
  `proceed` — verdict `approve` (no blocker/major) **and** QA green — per
  `review_loop_decision`; if the N = 3 budget is exhausted still on `changes` (`escalate`), develop
  stops and surfaces the findings — it does not merge.
- QA ran (existing + new + e2e); any surfaced defect was fixed, not masked.
- Assumptions surfaced; the main checkout untouched; the worktree removed after merge/abandon.
