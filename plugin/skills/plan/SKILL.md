---
name: plan
description: Turn a technical design into a dependency-ordered WORK plan — the build order — break the work into implementation tasks with dependencies, checkpoints, and deferred items, written to plan.md. (A "test plan" or "QA plan" is NOT this — that's qa-test-strategy.) Use to plan or sequence the engineering WORK — break a design into tasks, order the build, make a work/implementation plan. Not the technical design (architecture), writing code (develop), requirements (product), or a test/QA plan (qa-test-strategy).
allowed-tools: Read, Grep, Glob, Task, Write
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

1. **Read the inputs.** Load `tech-design.md`
   (`handoff.load_artifact(..., expected_type="tech-design")`) and the `prd.md` for acceptance
   context. Pick the `<feature-slug>`.
2. **Decompose.** Break the design's components into discrete, individually shippable tasks.
3. **Sequence.** Delegate ordering to the built-in `Plan` agent (fork via `Task`): establish
   dependencies between tasks (a DAG — no cycles) and the build order.
4. **Checkpoints & deferred.** Define verifiable checkpoints (milestones / definition of done
   per task) and an explicit list of deferred / out-of-scope items.
5. **Write the plan.** Produce `plan.md` (frontmatter `type`, `feature`, `status`, `tasks[]` with `id` + `deps`,
   `checkpoints[]`, `deferred[]`; body = task detail) under `docs/sdlc/<feature-slug>/`;
   validate it (`handoff.validate_header(..., expected_type="plan")`). Every design component
   must be covered by a task.

## Output

A `plan.md` handoff (see [patterns/handoff.md](../../patterns/handoff.md)): a dependency-ordered
task list with checkpoints and deferred items — the input to `develop`.

## Definition of done

- `plan.md` validates against the plan handoff schema (tasks with ids).
- Tasks cover the tech-design's components; dependencies form a cycle-free order.
- Checkpoints and an explicit deferred list are present.
- Only a plan — no code and no new design decisions (surface design gaps back to `architecture`).
