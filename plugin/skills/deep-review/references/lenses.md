# Review lenses by target type

Each lens is one focused angle for an independent reviewer. Pick the lenses that fit the
target; one reviewer per lens, prompted adversarially, returning structured findings
(`severity`, `location`, `issue`, `evidence`, `suggested fix`). See the
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
- **Robustness at seams** — code parsing external / LLM / tool output: does it handle
  malformed input (prose-wrapped JSON, stray tokens, empty)? brittle greedy regex vs balanced
  parsing; retry/fallback on a bad response.
- **Safety defaults** — are protective behaviors enforced, not opt-in? (a sandbox/isolation
  that only holds when a flag is passed is a latent hazard).

## Docs

- **Contradictions** — claims that disagree across (or within) documents; status flags that
  conflict; numbers/paths/ids that don't match.
- **Claims vs reality** — statements checked against the code/files: paths, symbols, flags,
  thresholds, versions, commands that don't match what exists.
- **Completeness & gaps** — undefined terms, concepts introduced but never explained or used,
  missing reading paths, dangling cross-references.
- **Clarity & ambiguity** — wording open to two readings; over-promising vs what exists.
- **Currency** — is a living doc stale against the latest ADR/decision? field-name or
  vocabulary drift across docs that describe the same thing.

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

## Eval / test harness

When the artifact is an eval, a fixture, or a test harness:

- **Fixtures actually run** — imports resolve; test files are discoverable (`test_*.py`); the
  planted defect is really present and the "clean" case is really clean.
- **Isolation / no-leak** — a write role or tool operates only in its sandbox and never mutates
  the real repo; verify (e.g. by checksum) rather than assume.
- **Determinism / reproducibility** — independent of run order and shared state; the recorded
  numbers are reproducible.
- **No degenerate pass** — assertions can't be satisfied by empty or garbage output (pair each
  negative assertion with a positive one).

## Cross-cutting (any target)

- **Completeness critic** — "what's missing — a lens not run, a claim unverified, a file not
  read?" Its answer becomes the next round.
- **Living catalog** — when a review surfaces a new failure mode, add it here as a lens so
  future reviews catch it, rather than only fixing the instance.
