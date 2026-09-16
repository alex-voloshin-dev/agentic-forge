# ADR 0096 — Validate the file you wrote, not the header you built

Status: Accepted (implemented)
Date: 2026-09-16

## Context

The first Tier-3 run on the post-audit fixtures put all five scenarios through live sessions.
Four passed. `quality-gate` failed on one checkpoint — `test-strategy.md valid` — and the diagnosis
is worth more than the failure:

The artifact was **there**, and it was good. A hundred-plus lines of scope, five risk areas, a
prioritized case list traced back to them, the invalid-input contract correctly identified as the
highest-value area to pin down. One value in its frontmatter was malformed:

```yaml
  - id: C7
    then: [h1, h2, h3, n1] — same-priority ties keep insertion order, not id-desc or reverse
```

A flow sequence with prose after it is not YAML. `load_artifact` raised, the checkpoint read
`None`, and a phase that had done its job correctly was scored a failure.

The skill had followed its own instructions. Step 3 says to validate with
`handoff.validate_header(header, expected_type="test-strategy")` — and `validate_header` takes a
**dict**. A model that assembles a header in its head, validates that, and then *types* the
frontmatter into a file has validated something other than what it wrote. The check and the
artifact were never connected.

This is not one skill's slip. Thirteen skills write a handoff artifact, and **all thirteen** said
`validate_header`; **none** re-read the file. The consequence in the field is worse than in the
eval: the phase that writes a malformed artifact reports success, and the failure surfaces one
phase later, in the consumer, against the wrong skill.

## Decision

1. **Every skill that writes a handoff artifact reads it back.** After writing, `load_artifact(
   <path>, expected_type=...)` and fix what it raises. One sentence added to each of the thirteen
   writing steps, naming why: `validate_header` checks a dict, not the YAML you typed.
2. **The handoff pattern says which validation counts.** `plugin/patterns/handoff.md` now states
   that validating the *file* is the only check that sees what was typed, with this failure as the
   worked example.
3. **No code changes.** `load_artifact` already does exactly this; nothing was missing but the
   instruction to point it at the artifact instead of at a dict. A helper that wrote *and*
   validated would be the stronger fix, but the skills compose their frontmatter in prose as they
   draft — there is no writer to hook — so the round-trip is the change that fits how they work.

## Consequences

- The `quality-gate` scenario re-runs on this change; the other four Tier-3 scenarios passed and
  are unaffected.
- This is the fourth instance of one shape in three days: a check that measures something adjacent
  to the thing it claims to check. The weekly eval measured a skipped step (ADR 0082); the
  activation eval measured an empty directory (ADR 0090); the Tier-2 assertions measured a grader
  that could not open a zip (ADR 0094, amended); and here a validator measured a dict rather than a
  file. The question that finds all four is the same one: *between what this check reads and what
  it claims about, what is in the gap?*
- Tier-3 earned its cost here. Tier-0 cannot see this (the file is written at runtime), Tier-1
  routes rather than produces, and Tier-2 grades a skill in isolation — only a chain that hands an
  artifact from one phase to the next fails the way the field fails.
