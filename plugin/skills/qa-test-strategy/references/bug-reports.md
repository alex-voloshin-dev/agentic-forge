# Bug reports & exploratory testing (qa-test-strategy reference)

Load for the two QA genres outside the strategy artifact: writing a defect up properly, and an
unscripted risk hunt. Both feed the strategy (a strong exploratory pass reshapes the risk areas).

## Structured bug report

A report an engineer can act on without a call:

- **Title** — symptom + scope in one line ("Export drops rows with unicode names, CSV only").
- **Environment** — version/commit, OS/browser, config that matters.
- **Minimal reproduction** — numbered steps from a clean state; the *smallest* input that still
  fails (attach it). If it reproduces only sometimes, say the observed rate.
- **Expected vs actual** — one line each, concrete ("expected 200 with 3 rows; got 500").
- **Evidence** — the failing output verbatim: log lines, stack trace, screenshot/response body.
- **Severity + rationale** — blocker / major / minor / nit, tied to user impact, not effort.
- **Suspicions (optional, labelled)** — a guess at the cause is welcome but marked as a guess.

No evidence, no report: a claim that cannot be reproduced or shown gets logged as a question,
not a defect.

## Exploratory testing pass

Time-boxed, charter-driven, documented:

1. **Charter** — one sentence: what area, what risk ("import pipeline under malformed CSVs").
   Pick charters from what changed recently + what fails expensively.
2. **Tours** — vary systematically: happy path, then invalid/boundary input (empty, huge,
   unicode, negative, concurrent), then state transitions (cancel mid-flow, retry, back button,
   session expiry), then environment (slow network, small viewport).
3. **Note as you go** — every surprise, even non-bugs (confusing copy, slow spots); they inform
   the strategy's risk areas.
4. **Report** — findings as structured bug reports (above) with severity; plus a coverage note:
   what was toured, what was NOT (so silence reads as "not checked", never "clean").
