# Review lenses by target type

Each lens is one focused angle for an independent reviewer. Pick the lenses that fit the
target; one reviewer per lens, prompted adversarially, returning structured findings
(`severity`, `location`, `evidence`, `suggested fix`). See the
[adversarial-review pattern](../../../patterns/adversarial-review.md).

## Code / diff / PR

- **Correctness & bugs** — logic errors, edge cases (empty/null/overflow), off-by-one,
  error handling, concurrency, resource leaks.
- **Reuse & simplification** — duplicated or reinvented logic (e.g. a manual loop that is a
  built-in), dead code, needless complexity, clearer equivalents.
- **Security** — injection, unvalidated input, authz/authn gaps, secrets, unsafe defaults.
- **Tests & coverage** — missing/weak tests, tests that assert nothing, untested edge cases,
  tests weakened to pass.
- **Contract & API** — breaking changes, signature/behavior drift, back-compat.

## Docs

- **Contradictions** — claims that disagree across (or within) documents; status flags that
  conflict; numbers/paths/ids that don't match.
- **Claims vs reality** — statements checked against the code/files: paths, symbols, flags,
  thresholds, versions, commands that don't match what exists.
- **Completeness & gaps** — undefined terms, concepts introduced but never explained or used,
  missing reading paths, dangling cross-references.
- **Clarity & ambiguity** — wording open to two readings; over-promising vs what exists.

## Design / architecture / ADR

- **Alternatives weighed** — was a real alternative considered and compared, or asserted by
  fiat? (an ADR without discarded options is not an ADR).
- **Risks & trade-offs** — unstated failure modes, scaling/latency, data loss, idempotency,
  operational cost.
- **Requirement coverage** — does every requirement/goal map to a component or explicit
  decision? any orphan requirements or unjustified components?
- **Consistency with prior decisions** — does it contradict existing ADRs/constraints
  without superseding them?

## Working tree / change set

Use the code lenses scoped to the diff, plus:

- **Blast radius** — what else the change touches or breaks; migrations; callers.
- **Docs/tests in lockstep** — were the docs and tests updated with the change (per the
  project's documentation/test discipline)?

## Cross-cutting (any target)

- **Completeness critic** — "what's missing — a lens not run, a claim unverified, a file not
  read?" Its answer becomes the next round.
