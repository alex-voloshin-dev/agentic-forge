<!--
Thanks for contributing! Read CONTRIBUTING.md first. The one rule:
contract → evals → implementation → gate. Keep the Tier-0 gate green and ship the
CHANGELOG + docs/ADR updates in the SAME PR.
-->

## What & why

<!-- What does this change, and why? Link the issue / ADR if there is one. -->

Closes #

## Type of change

- [ ] New component (skill / agent / script) — built contract → evals → implementation → gate
- [ ] Change to an existing component
- [ ] Bug fix
- [ ] Docs / ADR only
- [ ] Tooling / CI / eval-harness

## Gate (Tier 0 — must be green)

- [ ] `python dev/validate.py` passes
- [ ] `pytest -q --cov=agentic_forge --cov-fail-under=80` passes
- [ ] `ruff check .` clean
- [ ] `mypy plugin/lib plugin/hooks dev` clean

## Documentation discipline (same unit of work)

- [ ] `CHANGELOG.md` entry added (Added / Changed / Fixed / Removed)
- [ ] Affected docs under `docs/` updated
- [ ] Significant decision recorded as an ADR in `docs/architecture/decisions/`
- [ ] Explains *how* it works, not just that it exists

## Evals (if a gated component changed)

- [ ] Did not weaken the gate (no lowered threshold, no dropped assertion)
- [ ] Achieved eval numbers + model noted in the CHANGELOG (if Tier-1/2/3 were run)
- [ ] Added the `eval` label to run the cost-gated Tier-1/2 jobs (if needed)

## Notes for reviewers

<!-- Anything that helps the review: trade-offs, follow-ups, areas to look at closely. -->
