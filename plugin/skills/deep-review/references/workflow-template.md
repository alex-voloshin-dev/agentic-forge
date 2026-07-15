# Canonical Workflow template (multi-agent deep review)

Use this when the user has opted into multi-agent orchestration (a Workflow host): copy the
script skeleton and fill in the lenses — do **not** re-invent the harness or the schemas per run.
Field evidence for why: three production audits each hand-authored the orchestration from scratch,
their finding/verdict schemas drifted (`corrected_severity` vs `correctedSeverity` vs ad-hoc
`confidence` keys), and one audit lost two lenses to agent errors with no retry plan. Fixed
schemas make runs comparable and re-runnable; the retry loop makes them survive agent failures.

## Canonical schemas

One schema pair for every deep review. Do not rename keys between runs.

```javascript
const FINDINGS = {
  type: "object", required: ["lens", "findings"],
  properties: {
    lens: { type: "string" },
    summary: { type: "string" },
    findings: { type: "array", items: {
      type: "object",
      required: ["severity", "location", "issue", "evidence", "fix"],
      properties: {
        severity: { enum: ["blocker", "major", "minor", "nit"] },
        location: { type: "string" },      // file:line or doc/section
        issue: { type: "string" },
        evidence: { type: "string" },      // verbatim excerpt the reviewer actually saw
        fix: { type: "string" },
      },
    }},
  },
}

const VERDICT = {
  type: "object", required: ["verdict", "reasoning"],
  properties: {
    verdict: { enum: ["CONFIRMED", "REFUTED", "DOWNGRADED"] },
    correctedSeverity: { enum: ["blocker", "major", "minor", "nit"] },  // when DOWNGRADED
    reasoning: { type: "string" },
    sourceExcerpt: { type: "string" },     // what the verifier re-read at the location
  },
}
```

## Script skeleton

Review → verify runs as a pipeline (a lens's findings verify while other lenses still review);
a failed lens is retried once before it is reported as lost.

```javascript
export const meta = {
  name: 'deep-review',
  description: 'Adversarial multi-lens review with per-finding source verification',
  phases: [
    { title: 'Review', detail: 'one independent adversarial reviewer per lens' },
    { title: 'Verify', detail: 'independent re-read of every finding at its location' },
  ],
}
const LENSES = [/* from references/lenses.md, e.g. */ 'correctness', 'security', 'data-model']
const TARGET = args?.target ?? 'the working tree'

async function reviewLens(lens) {                    // retry-once: agent() returns null on error
  for (let attempt = 1; attempt <= 2; attempt++) {
    const r = await agent(
      `Adversarial ${lens} review of ${TARGET}. Assume defects exist and hunt them; ` +
      `every finding MUST cite file:line evidence you actually read. Return findings only.`,
      { label: `review:${lens}`, phase: 'Review', schema: FINDINGS })
    if (r) return r
    log(`lens ${lens}: attempt ${attempt} failed${attempt < 2 ? ', retrying' : ''}`)
  }
  return { lens, findings: [], summary: 'LENS LOST: agent failed twice' }   // never silent
}

const results = await pipeline(
  LENSES,
  lens => reviewLens(lens),
  review => parallel(review.findings.map(f => () =>
    agent(`Verify at ${f.location}: "${f.issue}". Re-read the source there; default to REFUTED ` +
          `if the evidence does not hold. Severity claimed: ${f.severity}.`,
          { label: `verify:${f.location}`, phase: 'Verify', schema: VERDICT })
      .then(v => ({ ...f, lens: review.lens, verdict: v }))))
)
const flat = results.flat().filter(Boolean)
const lost = LENSES.filter(l => !flat.some(f => f.lens === l))
if (lost.length) log(`lenses with no surviving output: ${lost.join(', ')}`)   // no silent caps
return {
  confirmed: flat.filter(f => f.verdict?.verdict === 'CONFIRMED'),
  downgraded: flat.filter(f => f.verdict?.verdict === 'DOWNGRADED')
      .map(f => ({ ...f, severity: f.verdict.correctedSeverity ?? f.severity })),
  refuted: flat.filter(f => f.verdict?.verdict === 'REFUTED'),
  lostLenses: lost,
}
```

## Rules that make it work

- **Retry a lens, not the audit.** `agent()` returning `null` (skipped/errored) is expected;
  retry that lens once, then record it as lost — a re-run of only the lost lenses is a small
  follow-up workflow, not a fresh audit.
- **Disclose losses.** `lostLenses` (and any cap you applied) goes in the final report — a lost
  lens must read as "not checked", never as "clean".
- **Verify with REFUTED as the default.** The verifier re-reads the source at `location`;
  plausible-but-unverified findings die here. `DOWNGRADED` keeps a real-but-overstated finding
  with `correctedSeverity`.
- **Dedup before verify only if lenses overlap heavily** (same file:line + same issue), and note
  the merge; otherwise pipeline straight through — the barrier costs wall-clock.
- **Resume, don't restart.** The Workflow host caches completed `agent()` calls by (prompt,
  opts); re-invoking with the same script re-runs only what changed or failed.
- The synthesis/dedup/severity-ordering and the report shape stay as SKILL.md defines them —
  this template only standardizes the fan-out mechanics.
