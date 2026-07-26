# 0066 — Every artifact-writing skill must demand valid YAML frontmatter

Status: Accepted — **implemented**. Generalises a fix that had been applied locally in
[0023](0023-stage6-design-onboarding.md)'s `ux-design` and in one E2E scenario's prompt; hardens the
handoff contract of [0010](0010-handoff-schemas-and-pattern-references.md) /
[0032](0032-handoff-contract-guard.md).

## Context

The **first live Tier-3 run** after the review-loop sweep failed the `spine` scenario on two phases:

```
[architecture] FAIL   [FAIL] tech-design.md exists and validates
[plan]         FAIL   [FAIL] plan.md exists and validates
```

The artifacts existed. They failed to *parse*:

```
tech-design.md: invalid YAML in frontmatter: mapping values are not allowed here
  line 14: ... New module-level mapping {"high": 0, "normal": 1, "low": 2} serv ...
plan.md:        invalid YAML in frontmatter: mapping values are not allowed here
  line 20: ... PRIORITY_RANK == {"high": 0, "normal": 1, "low": 2}. Pre ...
```

An unquoted colon inside a frontmatter list entry ends the value and makes the line look like a
mapping. One such value invalidates **the whole artifact** — every downstream phase that calls
`handoff.load_artifact` gets nothing.

The revealing part is where the guidance already lived. `ux-design` (ADR 0023) says *"quote any
value containing a colon"*, and the `product-inception` E2E scenario repeats it in two of its
prompts. **Nobody else did.** So this failure had been hit before, and was patched twice in the two
places where it hurt — never generalised. `architecture`, `plan`, `product`, `research` and
`marketing` all instruct a model to write YAML frontmatter and none of them warned about it; the
`spine` scenario had been passing on luck, with content that happened not to contain a colon.

## Decision

**Every skill that instructs a model to write frontmatter states the constraint, with a concrete
example of a value that trips it.** Added to `architecture`, `plan`, `product`, `research`,
`marketing` (matching `ux-design`, unchanged) — six of six now carry it.

Each phrasing names *its own* likely offender, because an abstract rule is easy to skim past:

| Skill | Example given |
| --- | --- |
| `architecture` | a risk describing `{"high": 0}` |
| `plan` | a checkpoint asserting `PRIORITY_RANK == {"high": 0}` |
| `product` | an acceptance criterion naming `{"high": 0}` |
| `research`, `marketing` | a cited source URL — which **always** contains `https:` |

Each also states the consequence — *the whole artifact fails to parse for the downstream phase* —
so the rule reads as load-bearing rather than stylistic.

## The fix belongs in the skill, not the eval prompt

The tempting one-line fix was to copy the hint into the `spine` scenario's prompts, as
`product-inception` already does. **Rejected:** that makes the test green while every real user
running `/architecture` in their own repository still produces an unparseable artifact. The E2E
prompt is a *test fixture*; the skill is the product. Patching the fixture to match a broken product
is how the gap survived this long — it was already patched in one scenario, which is precisely why
nobody noticed the skills were missing it.

The scenario prompts are deliberately left as they are, so they keep testing what a *thin* prompt
plus a *complete skill* produces.

## Alternatives considered

- **Validate and auto-repair the frontmatter in `handoff`:** rejected — silently rewriting a model's
  artifact hides the defect and makes the schema a suggestion. The artifact should be written
  correctly; `validate_header` failing loudly is the right behaviour.
- **Only fix `architecture` and `plan` (the two that actually failed):** rejected — `research` and
  `marketing` embed cited **URLs**, which contain a colon by construction, so they are *more* exposed,
  not less. Fixing only the observed failures is what produced this ADR's context.
- **Add a Tier-0 lint that greps skill bodies for the phrase:** deferred — it would enforce wording
  rather than behaviour, and the handoff-contract guard (0032) already covers the *fields*. If this
  regresses, a check belongs there.

## Consequences

- All six artifact-writing phases state the constraint; the failure mode is now addressed at the
  point where the artifact is authored, not in one scenario's fixture.
- Tier-3's `spine` scenario should stop failing intermittently on artifact validity — this is
  offered as the expected outcome, and the re-run is what confirms it.
- The episode is also an argument for running Tier-3 **live** on changes to the spine phases: the
  dry run (wiring only) was green throughout, and Tier-0/1/2 all passed. Only the live E2E — which
  actually asks a model to write the artifact and then parses it — could surface this.
