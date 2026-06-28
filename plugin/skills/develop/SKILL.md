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
   (`handoff.load_artifact(..., expected_type="plan")`) and/or `tech-design.md`; derive
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
3. **Implement.** Delegate to the [`software-engineer`](../../agents/software-engineer.md) role
   (fork via `Task`), **passing the worktree path**; it re-derives the stack profile there (the
   same `stacks` helper, so the result matches step 1) and loads `engineering-standards` + the
   detected `<stack>-patterns` pack (e.g. `python-patterns`; if the profile has no pack, the
   standards + the profile's toolchain), writes the code and its tests in the worktree, and
   reports files/tests/assumptions. Keep the change scoped to the step.
4. **Integrate, then review.** When a level's worktrees finish, **integrate** them — merge each
   into the base branch in a deterministic order (e.g. by task id), resolving conflicts
   ([worktree-parallel.md](../../patterns/worktree-parallel.md)). Then produce the integrated diff
   — `git -C <repo> add -A && git -C <repo> diff --staged` (staging so new files are included) — and
   pass that diff text to the [multi-aspect review](../../patterns/multi-aspect-review.md) (the
   `code-review` engine: `reviewer` + `security-engineer` + the stack's lint/type tools from the
   profile/repo). The reviewers receive the diff as input and need no git access. Aggregate to one
   approve/changes verdict. **Advance to the next dependency level only after this one integrates,
   is approved, and its QA is green.**
5. **Loop back (bounded).** On `changes`, return the findings to step 3 and revise — bounded at
   **N = 3** (see [patterns/review-loop.md](../../patterns/review-loop.md)). If N = 3 is
   exhausted and the verdict is still `changes`, **do not proceed or merge** — surface the
   unresolved findings to the user and stop. On `approve`, proceed.
6. **QA.** Delegate to the [`qa-engineer`](../../agents/qa-engineer.md) role (passing the
   worktree path): strengthen the suite (existing + new unit + end-to-end) and run it. A
   surfaced defect re-enters at step 3 → step 4 (re-review) → step 6, under the **same N = 3
   budget**; if still failing at the budget, surface the defect and stop. Never weaken a test
   to pass.
7. **Hand off and clean up.** On `approve` + green suite: the worktree holds the reviewed,
   tested change, ready to merge. Report the change summary. **develop owns the worktree
   lifecycle — remove the worktree (`git worktree remove`) once the change is merged or
   abandoned, even on failure** (worktree.md).

## Output

The worktree change (tests green), a structured change summary (files, tests, assumptions), and
the review verdict. The main checkout is never modified. (The canonical `review.md` handoff is
the `code-review` phase's artifact, not develop's; develop's gate is the verdict that drives
the loop.)

## Definition of done

- The plan step is implemented in a worktree, scoped, with tests added and the suite green.
- The multi-aspect review verdict is `approve` (no blocker/major) before QA sign-off; if the
  N = 3 budget is exhausted still on `changes`, develop stops and surfaces the findings — it
  does not merge.
- QA ran (existing + new + e2e); any surfaced defect was fixed, not masked.
- Assumptions surfaced; the main checkout untouched; the worktree removed after merge/abandon.
