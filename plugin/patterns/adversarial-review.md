# Pattern: adversarial fan-out review

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
2. **Fan out** one **fresh, independent** reviewer per lens — a forked `reviewer` role or a
   general-purpose subagent with *no* prior context (so it can't inherit the author's
   assumptions). Prompt each **adversarially** ("assume problems exist; hunt them") and make
   it return a **structured** result: per finding — `severity`, `location`, `issue`, `evidence`,
   `suggested fix`. Run them concurrently (Task fan-out; a Workflow when the user opted in).
3. **Verify** every substantive finding against the source before accepting it. Reviewers
   produce false positives and hallucinations — confirm the claim is real (open the file,
   re-run the check). Drop or downgrade what doesn't hold; record notable false alarms with
   the reason. *This step is what separates a trustworthy review from a pile of guesses.*
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
