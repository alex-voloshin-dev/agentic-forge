# Pattern: multi-aspect code review

Review a code change by fanning out **one reviewer per aspect** — correctness/bugs, security,
integration + API, and style/lint/warnings — then verify and synthesize a single verdict with
findings. It is [fan-out/fan-in](fan-out-fan-in.md) specialised for code, and it is the review
gate inside the `develop` workflow and the engine of the `code-review` phase. For non-code
targets (docs, design) use [adversarial-review.md](adversarial-review.md) / `deep-review`.

## Aspects (the partition)

| Aspect | Looks for | Executor |
| --- | --- | --- |
| **Correctness / bugs** | logic errors, edge cases, error handling, concurrency, leaks | `reviewer` / `software-engineer` (or stack engineer) |
| **Security** | injection, authz/authn, secrets, unsafe defaults, supply chain | `security-engineer` |
| **Integration + API** | contract/back-compat breaks, signature/behavior drift, cross-service effects | `reviewer` / the relevant stack engineer |
| **Style / lint / warnings** | formatter, linter, type, and compiler warnings | deterministic tools first (run them), then `reviewer` for what tools miss |

Add an aspect only when the change warrants it (assess per case — e.g. a DB migration adds a
data-safety aspect). The style aspect runs the project's real tools (ruff/mypy/eslint/…) and
treats their output as evidence, not opinion.

The specialist executors (`software-engineer`, `security-engineer`, stack engineers) are the
gated Stage 2 roster (see [../../docs/architecture/spine.md](../../docs/architecture/spine.md)
and [ADR 0014](../../docs/architecture/decisions/0014-software-engineer-base-role.md)); until a
role ships, that aspect falls back to the generic `reviewer` with an aspect-specific prompt.

## The method

1. **Scope** the diff and pick the aspects that apply.
2. **Fan out** one reviewer per aspect (independent, structured findings: `severity`,
   `location`, `issue`, `suggestion`, `evidence` — the canonical shape in
   [handoff.md](handoff.md)) — see fan-out/fan-in.
3. **Verify** each finding against the source (open the file, re-run the tool/test). Drop or
   downgrade what doesn't hold.
4. **Synthesize one verdict.** Aggregate across aspects: **any `blocker` or `major` from any
   aspect → `changes`**; otherwise `approve`. Dedupe overlapping findings; when two aspects
   rate the same finding differently, **keep the highest severity**. Write a `review.md`
   artifact (see [handoff.md](handoff.md)) with the verdict + findings.

## In the `develop` workflow

This pattern is the **review gate** between implementation and QA: a `changes` verdict
**loops back** to implementation (bounded by [review-loop.md](review-loop.md)); `approve`
proceeds to QA. The standalone `code-review` phase runs the same method on a diff and
emits `review.md` for the spine.

## Composition

- Built on [fan-out-fan-in.md](fan-out-fan-in.md); bounded by [review-loop.md](review-loop.md);
  emits [handoff.md](handoff.md) `review.md`; reuses the `reviewer` role and Stage 2 specialist
  roles. `deep-review` / [adversarial-review.md](adversarial-review.md) cover non-code review.
