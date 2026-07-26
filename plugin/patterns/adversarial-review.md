# Pattern: adversarial fan-out review

*(ADR 0027.)*

A high-fidelity review that resists the blind spots of a single pass (especially an author's
own). Decompose the review into independent **lenses**, **fan out** one fresh reviewer per
lens, **verify** every finding against the source, then **synthesize** one deduplicated,
prioritized report. This is the review analogue of `deep-research`'s fan-out→verify→synthesize
harness; the `deep-review` skill orchestrates it.

## When to use

A non-trivial review where completeness and correctness matter: auditing docs/design for
contradictions and gaps, reviewing a sizeable change set, or getting an independent second
opinion. For a quick single-file diff lint, a single `reviewer` pass is enough — don't fan out.

## The method

1. **Decompose** the target into lenses appropriate to its type (see the lens catalog in
   `deep-review`'s `references/lenses.md`). Each lens is one angle a reviewer is blind to the
   others on.
2. **Fan out** one **fresh, independent** reviewer per lens — the `reviewer` role or a
   general-purpose subagent with *no* prior context (so it can't inherit the author's
   assumptions). **Never the `fork` subagent type**: a fork inherits the parent's context *and its
   standing directive*, which is both the assumption-leak this step exists to prevent and a licence
   to act — see [fan-out-fan-in.md](fan-out-fan-in.md#choosing-the-subagent-type). Because
   subagents cannot spawn subagents, these lenses must run at the **top level**; a lens claimed by
   the agent that wrote the code never ran. Prompt each **adversarially** ("assume problems exist; hunt them") and make
   it return a **structured** result: per finding — `severity`, `location`, `issue`, `evidence`,
   `suggested fix`. Run them concurrently (Task fan-out; a Workflow when the user opted in).
3. **Verify** every substantive finding against the source before accepting it. Reviewers
   produce false positives and hallucinations — confirm the claim is real (open the file,
   re-run the check). Drop or downgrade what doesn't hold; record notable false alarms with
   the reason. *This step is what separates a trustworthy review from a pile of guesses.*
3b. **Triage the lenses themselves before synthesizing** (ADR 0073). Open each lens's actual content: one
   that returns a placeholder, a single generic finding, or nothing *after a long tool run* is
   **degenerate, not clean** — the output-heaviest lenses are exactly the ones that die at the
   structured-output step, and they are not the redundant ones (one such re-run produced the
   highest-impact finding of its audit). Re-run failed and degenerate lenses in a second, smaller
   run with the same verify rigor plus the output caps in
   [fan-out-fan-in.md](fan-out-fan-in.md#output-discipline) — and **never by resuming the prior
   run id**, which replays the same failing prompt and serves the degenerate lens from cache as
   "done". A synthesis over unchecked lenses reports success it did not earn.
4. **Dedupe & prioritize** across lenses (and the author's own pass) by `severity`
   (`blocker | major | minor | nit`, as in [handoff.md](handoff.md)).
5. **Synthesize** one report: verified findings with concrete fixes, false alarms filtered
   (with reasons), and clean areas noted so silence is explicit, not an oversight.
6. **(Optional) apply & re-gate.** When asked to fix, apply the agreed findings, then re-run
   the relevant gate (Tier-0 / the eval gate) and report the result.

## Why each step

- **Fresh + independent** reviewers catch what the author and a same-context reviewer miss.
- **One lens each** keeps a reviewer focused and its output composable.
- **Adversarial prompting** raises recall (it surfaces problems a "looks-fine" pass skips).
- **Verification** keeps precision high — high recall without it just floods the caller.
- **Synthesis** turns N overlapping lists into one decision-ready report.

## Composition

- Each lens reviewer is the [`reviewer`](../agents/reviewer.md) role (or general-purpose).
- Use inside [review-loop.md](review-loop.md) as the high-fidelity reviewer step, and emit a
  `review.md` ([handoff.md](handoff.md)) so the outcome is auditable.
- Scale the fan-out to the ask: a few lenses for a focused review; the full catalog plus
  multi-vote verification for "audit everything".
- **External reviewer (independent lens, on by default).** When `external_reviewer.enabled`
  (settings, ADR 0041 — **on by default** since ADR 0057), an external CLI — `codex` (ADR 0042) —
  serves as an extra lens whose *different model* catches what a same-family pass misses. It is
  auto-invoked in **every workflow that writes a reviewable deliverable**, each on its own criteria:
  `develop` (`--kind code`), `product` (`--kind product`), `architecture` (`--kind technical`) and
  `plan` (`--kind plan`) since ADR 0060, `research` (`--kind research`) and `ux-design` (`--kind ux`)
  since ADR 0061, and `marketing` (`--kind marketing`) since ADR 0062. Run it via
  `${CLAUDE_PLUGIN_ROOT}/bin/external_review.py` (`--kind code|marketing|plan|product|research|technical|ux`, `--out
  review.md`); pick the kind that matches the deliverable — an unknown one falls back to the **code**
  criteria, which is wrong for a brief, spec, or design. It degrades
  gracefully when absent. It runs **read-only**; it sends the target to a third-party agent, so
  **set `external_reviewer.enabled: false` on secret-bearing repos**, and treat its findings as
  advisory (prompt-injectable).
