---
name: plan
description: Turn a technical design into a dependency-ordered WORK plan — the build order — break the work into implementation tasks with dependencies, checkpoints, and deferred items, written to plan.md. (A "test plan" or "QA plan" is NOT this — that's qa-test-strategy.) Use to plan or sequence the engineering WORK — break a design into tasks, order the build, make a work/implementation plan. Not the technical design (architecture), writing code (develop), requirements (product), or a test/QA plan (qa-test-strategy).
allowed-tools: Read, Grep, Glob, Bash, Task, Write
---

# Plan (phase workflow)

The planning phase of the SDLC spine: turn a tech design into the dependency-ordered task plan
that `develop` executes. It delegates the sequencing to the built-in `Plan` agent and owns the
handoff.

## When to use

After a tech design exists and the question is *in what order to build it*: task breakdown,
dependencies, checkpoints, what's deferred. Not for the design itself (`architecture`),
requirements (`product`), or implementation (`develop`).

## Process

> **Recall first** — pull the project's relevant prior decisions from the knowledge vault (see
> [knowledge-recall](../../patterns/knowledge-recall.md)); factor them in, and skip if the vault is empty.

> **Deliver in isolation** — when a `<feature-slug>` is in play, write into the feature's
> shared documentation worktree rather than the checkout, and deliver the result as a pull
> request (see [doc-delivery](../../patterns/doc-delivery.md)). One worktree and one PR per
> **feature**, shared by every document phase — that is what lets the next phase read what
> this one wrote. Skip it for a one-off document outside a feature flow.

1. **Read the inputs.** Load `tech-design.md`
   (`handoff.load_artifact(..., expected_type="tech-design")`; **refuse to plan from it unless `handoff.is_handoff_ready(header)`**) and the `prd.md` for acceptance
   context. Pick the `<feature-slug>`.
2. **Decompose.** Break the design's components into discrete, individually shippable tasks.
3. **Sequence.** Delegate ordering to the built-in `Plan` agent (fork via `Task`): establish
   dependencies between tasks (a DAG — no cycles) and the build order.
4. **Checkpoints & deferred.** Define verifiable checkpoints (milestones / definition of done
   per task) and an explicit list of deferred / out-of-scope items.
5. **Write the plan, then validate it.** Produce `plan.md` (frontmatter `type`, `feature`, `status`, `tasks[]` with `id` + `deps`,
   `checkpoints[]`, `deferred[]`; body = task detail; **valid YAML — quote any value containing a
   colon**, e.g. a checkpoint asserting `PRIORITY_RANK == {"high": 0}`, or the whole artifact fails
   to parse for `develop`) under `docs/sdlc/<feature-slug>/`;
   validate it (`handoff.validate_header(..., expected_type="plan")`) **and confirm the graph
   resolves** — `planning.plan_batches(tasks)` (from `${CLAUDE_PLUGIN_ROOT}/lib`, the same helper
   `develop` batches with) raises on a duplicate id, an unknown dependency, or a cycle, so a clean
   run is the deterministic proof of a cycle-free order. Every design component
   must be covered by a task.
6. **Skeptic pass (bounded).** Before handing off, fork a fresh `reviewer` (via `Task`) to attack
   the plan adversarially — every design component **covered** by a task, the dependency graph
   **complete** (no missing edge that would break the build order) as well as acyclic, each task
   **independently shippable** with a **verifiable** checkpoint, and the deferred list **explicit**
   (nothing silently dropped) — then revise worst-first. **External reviewer lens (on by default,
   ADR 0057/0060):** when `external_reviewer.enabled` (settings), also run the external reviewer over
   `plan.md` — call `external_review.review(plan_text, "plan", command=<cfg>)` from
   `${CLAUDE_PLUGIN_ROOT}/lib` (repo-side equivalent: `dev/external_review.py --target
   docs/sdlc/<feature-slug>/plan.md --kind plan`); codex critiques the plan as an
   independent-model lens (completeness, task sequencing, risk) and its `findings` fold into the same
   worst-first revision. It **degrades gracefully** (absent/disabled codex is skipped, not a failure)
   and its findings are **advisory** (prompt-injectable) — verify before acting. **Persist each round** — one `review-<artifact>-<iteration>.md` per round under `docs/sdlc/<feature-slug>/`, aggregating **both** lenses; on `proceed` keep only the final round, on `escalate` keep them all (naming + lifecycle: [review-loop.md](../../patterns/review-loop.md)). **Exit criterion
   (the shared, tested rule):** each round, compute `handoff.review_loop_decision(verdict, iteration,
   cap=3, gate_green=<step 5 passes>)` (see
   [adversarial-review.md](../../patterns/adversarial-review.md), bounded by
   [review-loop.md](../../patterns/review-loop.md)) — `revise` (loop back and fix worst-first),
   `escalate` (still `changes` at N = 3 → **commit nothing; mark the feature PR a draft** (the merge gate already refuses a draft), set the artifact's `status` to `in-review`, surface the unresolved gaps and stop; the status is what makes "don't hand off" enforceable — the file is already on disk), or
   `proceed` (**commit this phase's artifact and push — opening or updating the feature PR per [doc-delivery](../../patterns/doc-delivery.md)**; `approve` **and** the plan validates → the plan is done). Don't hand off a plan that
   leaves a design component uncovered or a checkpoint unverifiable.

## Output

**A full plan run produces the finished build order: a validated `plan.md`** (see
[patterns/handoff.md](../../patterns/handoff.md)) — a dependency-ordered task list with checkpoints
and deferred items — that survived the bounded skeptic loop to `proceed`, ready as the input to
`develop`. A run whose loop `escalate`s (unresolved gaps at N = 3) surfaces them and stops; it does
**not** hand off an incomplete plan.

## Definition of done

- The skeptic loop exited on `proceed` (`review_loop_decision`): `approve` **and** the step-5
  validation green — not `escalate`.
- `plan.md` validates against the plan handoff schema (tasks with ids).
- Tasks cover the tech-design's components; dependencies form a cycle-free order (`plan_batches`
  resolves).
- Checkpoints and an explicit deferred list are present.
- A bounded skeptic pass (plus the external-reviewer lens when enabled) checked component coverage,
  sequencing, and checkpoint verifiability.
- Only a plan — no code and no new design decisions (surface design gaps back to `architecture`).
