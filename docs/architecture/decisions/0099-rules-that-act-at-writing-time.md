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
   post file (`wc -m`) and state the counts in the report; a file outside its band is not
   finished. And **a post file is the post**: its whole contents are what gets published, so no
   title heading and no editorial note — publishing guidance belongs in the report and the
   calendar. (The first wording said "headings excluded", which accommodated the ambiguity
   instead of removing it; see below.)
3. **One assertion was split, and not because it was inconvenient.** "The X post fits in 280
   characters" asks the grader for a measurement its tools cannot make — `Read`, `Grep`, `Glob`
   and no way to count. That is ADR 0094's own C6d class, and it sat unnoticed in a contract this
   series had read twice. It becomes two claims a reader can check: the report *states* each
   count and each is in band, and each file *is* the post, the two not duplicates. The other
   assertion — the trust boundary — was right as written and stands untouched; the change went
   where the model reads at writing time.

## What the re-runs said

`engineering-standards` went **0.857 → 1.000**: the 5/5 assertion is gone, first time. Separating
the two duties was the whole fix.

`marketing` took two more passes, and both are the same lesson again.

*Pass one.* The rule worked — the session counted and reported 1,349 and 280 characters, both in
band — and the assertion still failed 5/5, because the **files** were 1,453 and 347: a title
heading, an editorial note and a separator sat on top of each post. My own wording ("headings and
file names excluded") had *accommodated* the ambiguity instead of removing it. So: **a post file
is the post** — its whole contents are what gets published, no heading, no note, and `wc -m`
counts the file. Publishing guidance goes in the report and the calendar, never in the file
someone copies into the box. The next probe wrote 1,336 and 253 characters, clean.

*Pass two.* Still 5/5 — and this time the product was right and the **assertion** was not. It
reads "the X post fits in 280 characters"; the grader has `Read`, `Grep` and `Glob` and **cannot
count characters**. It was being asked to eyeball a measurement, which is ADR 0094's own C6d class
(an assertion no grader tool can check) sitting unnoticed in a contract this series had already
read twice. Split in two, both verifiable: the report *states* each count and each is in band (the
skill now produces those numbers, so they are evidence, not a promise), and each file *is* the
post, the two not duplicates.

*Pass three.* Still 5/5, and the sample said why in one line: the report named no counts at all.
The measure-and-state rule lived in `references/content.md`, and `build_skill_system` injects the
SKILL.md body only — so the rule bound the sessions that happened to open the reference (my probes
did; the eval's did not). The rule moved into the body.

*Pass four.* The report now named numbers — *"LinkedIn is 847 (well within LinkedIn's ~3,000-char
limit)"* — against a band it had never seen, because I had moved the action into the body and left
the numbers in the reference. A half-move. The bands now sit beside the rule that uses them.

*Result:* `marketing` **PASS 0.985** (lower bound 0.965); the length assertion that failed 4/5,
then 5/5 four times, no longer appears. What remains is a 1/5 claim slip, which is what noise looks
like beside a systematic failure.

Five passes, five layers: the model's behaviour (estimating), the artifact's shape (a heading on
the post), the assertion's verifiability (a grader that cannot count), the rule's location (a
reference nobody opened), and the rule's completeness (an action without its numbers). Each was
invisible until the one before it was fixed, and each was named by the `sample` line rather than
guessed.

## Consequences

- Both contracts re-run on this change; the CHANGELOG entry records what the two assertions
  became.
- The pattern now has three instances in one day (frontmatter values, a verbatim path, these
  two): a rule the skill states in passing is followed in passing. The rules that hold are the
  ones phrased as an action at the moment of writing — *count the file*, *quote the line*,
  *check the value where it enters* — with the failure they exist for as the example.
- A passing Tier-2 number is no longer the end of a reading. The evidence lines under it are; a
  `failed 5/5` under a PASS is a product finding with the transcript already attached.
- Three passes over one assertion, and each found a different layer: the model's behaviour, then
  the artifact's shape, then the assertion's own verifiability. The rule that kept them honest was
  reading one session before each change — without it, the first fix would have been called a
  failure and the eval relaxed.
