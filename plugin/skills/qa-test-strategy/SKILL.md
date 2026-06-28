---
name: qa-test-strategy
description: Plan WHAT TO TEST for a change or feature — the test strategy / QA test plan covering risk areas, test levels (unit / integration / e2e / perf / security), and prioritized test cases — by delegating to the qa-engineer role, and record a test-strategy handoff. Use whenever the ask is about testing — "what's the test strategy", "plan how we should test X", "design a QA test plan", "what should we test, and at which levels". Here "plan" / "design" mean the TEST plan — not breaking work into a task plan (plan) or the technical design (architecture); not writing the tests (develop), reviewing existing code (code-review), or cutting a release (release).
allowed-tools: Read, Grep, Glob, Bash, Task, Write, Edit
---

# QA test strategy (phase workflow)

The test-planning phase: turn a feature, plan, or change into a **test strategy** — the risk
areas, the test levels to cover, and a prioritized case list — by delegating the test-design
judgement to the [`qa-engineer`](../../agents/qa-engineer.md) role, then recording a
`test-strategy` handoff. It plans *what and how to test*; it does not write the tests (that is
`develop`'s QA step). (Design: [quality-ops.md](../../../docs/architecture/quality-ops.md).)

## When to use

When the task is to decide what to test and at which levels for a change/feature — a test plan or
QA strategy, before or alongside building. **Not** for writing/hardening the tests (`develop`),
reviewing already-written code (`code-review`), or assembling a release (`release`).

## Process

1. **Read the inputs.** Load the feature/`plan.md`/`tech-design.md` or the code under change, and
   detect the stack (`stacks.primary(<repo>)`) so the levels and tools match the repo.
2. **Delegate the analysis.** Fork the `qa-engineer` role (via `Task`) with the feature/code and
   the question "what are the risk areas, the right test levels, and the cases that matter?" The
   role brings the test-design expertise; pass it the context, not just the prompt.
3. **Synthesize the strategy.** Aggregate into a `test-strategy` handoff artifact (`handoff` type
   `test-strategy`: `type`, `feature`, `status`, `scope`, `risks`, `test_levels`, `cases`), then
   validate it (`handoff.validate_header(header, expected_type="test-strategy")`; see
   [handoff.md](../../patterns/handoff.md)). Cover the real risk areas (boundaries, invalid/abusive
   input, concurrency, rounding/precision, failure modes).
4. **Prioritize.** Order cases so boundaries and error/abuse paths come first; call out the levels
   (unit / integration / e2e / perf / security) the change actually warrants — not a blanket list.

## Output

A `test-strategy` handoff: scope, risk areas, the test levels to cover, and a prioritized case
list — the input the `develop` phase (or an engineer) turns into actual tests. No tests are written.

## Definition of done

- The real risk areas are identified (boundaries, invalid/abusive input, concurrency, failure modes).
- More than one test level is covered where warranted; cases are concrete and prioritized (not vague).
- A valid `test-strategy` artifact is produced (non-empty `test_levels`); no test code is written.
