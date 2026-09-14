# ADR 0095 — The two ADR 0094 left: a budget nothing measured, a slug nobody resolved

Status: Accepted (implemented)
Date: 2026-09-14

## Context

ADR 0094's sweep closed ~50 findings and deliberately left two, both named in its consequences:

1. **The deploy digest could never read the pipeline.** `_deploy_digest` passed the repository
   *path* where `gh --repo` wants `owner/name`. Before 0094 that surfaced as
   `deploy-digest [production]: healthy — none — continue monitoring (0 recent runs)` — a failed
   fetch degrading to `[]` and `rollout_health([], [])` reading empty as healthy. 0094 made the
   failure honest (`unknown — source unavailable`), which is the right answer to the wrong
   question: the daily job still could not read a thing.
2. **The listing budget was a number in CLAUDE.md that nothing measured.** Every model-invocable
   skill's `name` + `description` sits in *every* session's context, and the router-discipline rule
   has said since ADR 0056 that "adding an on-listing skill (or growing a description) requires a
   budget review". Nothing computed the figure. It was recounted by hand twice in two years, and
   the count in CLAUDE.md (~2,530 tokens) had drifted from the tree (2,564) by the time the audit
   measured it — a rule enforced by memory, which is the shape ADR 0082 is about.

## Decision

1. **The slug is resolved from the checkout, and "no GitHub remote" is *unavailable*, not empty.**
   `connectors.slug_from_remote_url` parses the three spellings a remote carries (`git@github.com:`,
   `https://github.com/`, `ssh://git@github.com/`, with or without `.git`) and is strict about the
   host: a GitLab or Bitbucket remote yields `None`, because guessing a slug would query a
   repository that is not ours. `connectors.remote_slug(path)` reads `origin` through a seam.
   `pipeline_source` now takes **a checkout path or a slug** — it resolves a directory through
   `remote_slug` — and when `gh` is on PATH but no GitHub remote is, it returns the new
   `ops.UnavailablePipeline(reason)` rather than an empty in-memory source. That distinction is
   the whole point of ADR 0094's third shape: "no provider configured" is a silence we can report
   as nothing; "a provider that cannot answer" is an unknown, and the two must not share a return
   value.
2. **The listing budget is a Tier-0 ratchet, not a ceiling.** `validation.listing_budget` renders
   what a live session is shown — `- agentic-forge:<name>: <description>` per model-invocable skill
   — and `validate_listing_budget` fails above `LISTING_BUDGET_CHARS` (10,400; today's listing is
   10,257 over 17 skills, ≈2,564 tokens at the usual chars/4 estimate).

   A **ceiling** was the obvious design and it is wrong here. The guidance is ~1% of the model
   window, ~2,000 tokens on 200k; the listing is already at 1.0–1.3%, so a gate that failed
   "too big" would fail on the first run and be switched off within a day. A ratchet fails
   **growth**: a new on-listing skill (~600 chars) or a description that puts on weight trips it;
   an equal-length rewording — what four descriptions got in 2026.9.4 — does not. Raising the
   constant *is* the budget review, and it appears in the diff where a reviewer sees it.

   The figure prints on every `dev/validate.py` run, pass or fail. A measurement that only speaks
   when it fails is how the weekly eval stayed green and blind for six runs (ADR 0082).

## Consequences

- The daily `deploy_digest` job can read GitHub Actions for the first time, in any checkout with a
  GitHub `origin`. In one without, it says which repository it could not resolve.
- `pipeline_source`'s parameter widened (path *or* slug); the skill references that pass
  `'OWNER/REPO'` keep working unchanged.
- Tier-0 gained the one check that guards the scarcest resource the plugin has. The next time a
  skill is proposed for the listing, the gate asks the question CLAUDE.md has only ever asked the
  author to remember to ask.
- Three of the five longest descriptions (`deep-review` 788, `research` 787, `security-review` 695
  chars) are where headroom comes from if a skill has to be added; the budget error names them.
