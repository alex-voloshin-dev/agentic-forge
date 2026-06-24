# 0020 — Tier-2 assertions must be inspection-gradeable; fix failing gates by fidelity, never by lowering the threshold

Status: Accepted

## Context

The first live Tier-2 run (subscription, `claude` runner) put 7 of 13 skill gates below the
`mean - stddev >= 0.8` bar (lower bounds): skill-factory 0.454, engineering-standards 0.571,
jvm 0.672, knowledge 0.667, javascript 0.750, rust 0.778, dotnet 0.822. Per-assertion
root-causing (a `runs=1` diagnostic that dumps each assertion's pass/fail plus the grader's
evidence) showed the failures were **eval-design** issues, not skill weakness — and that each
could be "fixed" the wrong way, by softening the gate. CLAUDE.md makes thresholds the definition
of done and the eval pyramid the contract; the policy in force (project memory) is: **improve the
component to meet the bar; a genuinely mis-designed eval may be made a fairer, higher-fidelity
test, but never soften an assertion or lower the threshold.** This ADR records how that policy
resolved the 7 gates and the structural rule it exposed.

## Decision

- **A Tier-2 assertion MUST be verifiable by the read-only `grader` role** (tools:
  `Read, Grep, Glob`). The grader has no `Bash`, so it can never *run* a build, linter,
  formatter, test, or `dev/validate.py`. An assertion phrased as a toolchain *execution* —
  "dotnet build is clean", "cargo clippy clean", "the project builds via its wrapper", "eslint
  clean", "`dev/validate.py` reports no errors", "ruff + mypy pass" — is therefore **ungradeable
  by execution**: the grader can only *guess* from the work text, which is exactly the observed
  near-0.8 variance. Each was reframed to the **inspectable code-property it proxies** (compiles
  cleanly on inspection / clippy-clean idioms / no new `eslint-disable` / standard-compliant
  frontmatter + body length + resolvable references). The quality intent and the per-case
  assertion count are preserved; only the un-runnable phrasing changes. (dotnet, rust, jvm,
  javascript, skill-factory)
- **Root-cause per assertion before any fix**, then fix at the cause:
  - *Skill gap* → improve the skill. knowledge now invokes the **installed `agentic_forge.vault`
    module** (not a file path that is absent in the sandbox) and states the exact note frontmatter
    (`title`/`type`/`tags`); skill-factory now states the **canonical component locations**
    (subagents live at `plugin/agents/<name>.md`), which is why it had scaffolded one at the
    wrong path.
  - *Eval scenario gap* → make the case exercise the asserted concern. engineering-standards got
    a real `cart.py`/`test_cart.py` fixture and a concrete task (its empty-sandbox case made the
    software-engineer correctly refuse to "scaffold from nothing"); jvm case 2 now uses a
    value-type map key so the equals/hashCode assertion is actually tested rather than vacuously
    failing.
  - *Mis-stated convention* → correct the assertion to the real one. skill-factory's "script is
    documented by a script-type evals.json" became the real convention — **pytest is a script's
    contract**; the `script` component type is schema-reserved for future use.
- **The 0.8 threshold and `runs >= 5` are invariant.** No gate was made to pass by lowering a
  number or deleting an assertion.

## Alternatives considered

- **Install every toolchain (dotnet/gradle/cargo/node) in the eval environment so builds run.**
  Rejected: it does not fix the grading step — the grader stays read-only and would judge the
  *engineer's claim* that it built, not a build it ran itself; it also makes the eval
  heavy/non-portable (CI, any dev machine) and network-dependent. Inspection-grading is both
  cheaper and the only thing the grader can actually do.
- **Give the grader `Bash` so it can run gates.** Rejected: the grader must be read-only — it
  reads the work's artifacts to verify claims and must never mutate them; running build tooling
  also re-introduces the toolchain-portability problem.
- **Lower the threshold / delete the flaky assertions.** Rejected outright by policy — that hides
  the problem instead of fixing the eval's fidelity.
- **Split into a portable inspection tier plus a toolchain-gated execution tier.** Deferred:
  viable later if we want real build/lint runs on a CI runner that has the toolchains, but
  unnecessary for the quality signal the grader provides today; recorded as a possible follow-on.

## Consequences

- Tier-2 assertions across the stack packs (dotnet, rust, jvm, javascript), skill-factory,
  knowledge, and engineering-standards now read as inspection properties; grading is
  deterministic, so the near-0.8 variance from un-runnable claims disappears.
- A reusable authoring rule for future evals: **write assertions the read-only grader can verify
  by reading.** skill-factory's author guidance and the eval-runbook carry this rule.
- The `runs=1` per-assertion diagnostic is the standard first step when a Tier-2 gate fails.
- Before/after numbers (5 runs/skill) live in the CHANGELOG and eval-runbook, not here — this ADR
  records the decision, not the metrics log.

## Exit criteria

- All 7 reframed/improved gates re-validated at `runs >= 5` with `mean - stddev >= 0.8`; the 6
  already-passing gates unchanged.
- Tier-0 + pytest green; CHANGELOG + eval-runbook updated with before/after numbers and the
  read-only-grader rule.
