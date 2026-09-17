# ADR 0099 — Rules that act at writing time

Status: Accepted (implemented)
Date: 2026-09-17

## Context

The first Tier-2 run on the pinned harness (ADR 0097/0098) passed all five script-invoking
contracts — and its new evidence lines showed two assertions failing systematically behind those
passing numbers:

```
engineering-standards: PASS (mean=0.857, stddev=0.000, lower_bound=0.857, n=5)
    failed 5/5: User input is validated at the trust boundary
marketing: PASS (mean=0.969, stddev=0.017, lower_bound=0.952, n=5)
    failed 4/5: The X post fits in 280 characters and the LinkedIn post is substantially longer …
```

Both assertions encode a rule the skill itself states. The engineering-standards pack says
"Validate input at trust boundaries; parameterised queries (never string-built SQL/commands)".
The marketing content reference says "X — 280 chars; LinkedIn — the 1,300–1,900-char band". A
rule that the skill states and the model does not follow, four or five runs out of five, is a
product finding, not an eval defect — and by the ADR 0098 rule, one session each was read before
anything was changed.

**engineering-standards, case 2** (`find_by_name(conn, name)` over sqlite, a user-supplied name).
The engineer parameterised the query, added a SQL-injection test, and wrote in its report:
*"Because the name crosses a trust boundary, it's bound as a `?` parameter."* No check on `name` at
all — not emptiness, not type, not length. The bullet names two duties in one breath and the
model reads them as one: *parameterise* discharged *validate*.

**marketing, case 6** (a LinkedIn post and an X post from a positioning brief). LinkedIn: 806
characters, against a band whose floor is 1,300. X: ~292 characters of body, against 280. The
limits are stated; the model estimates length and does not count.

## Decision

These are the ADR 0096 shape — an instruction that names a property is weaker than one that acts
while the model writes — applied to two rules the skills already had.

1. **The security baseline separates the two duties and says what "validate" means.** A value
   that arrives from a user, a request, a file or the network gets an explicit check where it
   enters — type, emptiness, length or range, allowed shape — and a bad value is rejected with a
   clear error before it reaches a query, a command, a path or a template. Parameterising is the
   other duty: it prevents injection and still accepts an empty name, a 10 MB string or the wrong
   type, so it is not validation. The bullet says so, with the sentence the engineer wrote as the
   example of the conflation.
2. **The content limits become a measurement, not an estimate.** Before handing off, count each
   post's body (`wc -m`, headings and file names excluded) and state the counts in the report; a
   post outside its band is not finished. The reference keeps the bands and adds the step, with
   the eyeballed 806 / ~292 as the example.
3. **No assertion was relaxed.** Both assertions state the skill's own rule; both were right. The
   evidence line and the sample under it are what made "PASS with a 5/5 failure" visible, and the
   change goes where the model reads at writing time — the pack bullet, the reference step — not
   into the eval.

## Consequences

- Both contracts re-run on this change; the CHANGELOG entry records what the two assertions
  became.
- The pattern now has three instances in one day (frontmatter values, a verbatim path, these
  two): a rule the skill states in passing is followed in passing. The rules that hold are the
  ones phrased as an action at the moment of writing — *count the file*, *quote the line*,
  *check the value where it enters* — with the failure they exist for as the example.
- A passing Tier-2 number is no longer the end of a reading. The evidence lines under it are; a
  `failed 5/5` under a PASS is a product finding with the transcript already attached.
