---
type: release
feature: agentic-forge-2026.11.18
status: final
version: 2026.11.18
date: 2026-11-27
changelog:
  - "A skill's Output section describes the artifact only: nine skills drop the third copy of a guard that their Process step and Definition of done already state (field item 10). The release DoD now names every push, and the develop DoD names the QA-red case and the hand-off."
breaking: []
---
# Release 2026.11.18

Field item 10 (thread e079ac53).

## What changed

- **`## Output` describes the artifact, not its guards again.** Nine skills stated a guard three times: in a Process
  step, in the Definition of done, and again in `## Output`. The `## Output` copy is gone where the other two hold the
  whole rule:
  - `develop`: a run that cannot reach approve and green QA stops and does not hand off partial code;
  - `release`: nothing is tagged or pushed without an explicit request;
  - `repo-onboarding`: everything is grounded in the real code;
  - the review loop's `escalate` sentence in `plan`, `architecture`, `product`, `research`, `ux-design` and
    `marketing`.

  The bodies are 1,036 characters shorter. No `description` changed; the listing stays at 6,910 characters.
- **Two DoD lines now state the whole guard,** since `## Output` no longer backs them up:
  - `release`: "Nothing is tagged or pushed (no tag, commit or branch) without an explicit request." Step 5 adds
    "push nothing else".
  - `develop`: "still on `changes` or with QA red (`escalate`), develop stops and surfaces the findings — it does not merge
    or hand off."

## How it was checked

- Review: the reviewer approved. Its minor (the release push scope) and a nit (the develop DoD) were applied. The
  external lens (codex) approved. Details are in `review-code-1.md`.
- Tier-0: `dev/validate.py`, `ruff`, `mypy`, the full pytest suite, and `dev/hook_smoke.py` under Python 3.9.
- Tier-2 on the changed skills (Opus 5.5, n = 5, gate mean − σ ≥ 0.8), all passing:

  | Skill | Score |
  |---|---|
  | release | 1.000 |
  | repo-onboarding | 1.000 |
  | marketing | 0.970 |
  | ux-design | 1.000 |

  The first ux-design run hit rate limits (429) and measured only 4 sessions; the rerun measured 5.
- Tier-3 `spine`: passes.

## Not validated

- **Tier-3 `product-inception` fails, on this branch and on master 2026.11.17 alike.** The research, architecture and
  ux-design review loops stay on `changes` through the N = 3 budget and escalate: `review_decision: escalate`, status
  `draft`. So the downstream phases correctly refuse to build on them. The master baseline escalated on more phases
  than this branch did, so the cause is not this change. It is recorded as a known issue, and the follow-up is to find
  out why the review loops do not converge on this fixture under Opus 5.5.
- Tier-2 was not run for `develop`, `plan`, `architecture`, `product` and `research`. These are spine skills without
  their own Tier-2 (ADR 0017). The `spine` scenario covers the plan and develop path.
- Tier-1 and Tier-1b were not run: no description changed.
