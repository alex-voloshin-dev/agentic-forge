---
type: review
feature: agentic-forge-2026.11.10
target: master..release-2026.11.10
iteration: 3
verdict: approve
findings: []
---
# Review, final round (decision: proceed)

The develop review loop over the four field-bug fixes (ADR 0109) ran three rounds. Earlier rounds are not kept
(review-loop.md, rule 3): this file records the round that reached `approve`.

- **Round 1 (`changes`).** Lenses: four reviewers (one per fix), a security engineer, and the external codex lens.
  codex reviewed a 268 KB diff from a directory outside the repository, which is bug 2's fix working live. The
  majors, all fixed in round 1:
  - `npm exec --` could download a missing tool;
  - the gate could block through yarn, pnpm or bun;
  - an unreadable subdirectory made detection raise;
  - develop omitted `--repo`, so a repository's opt-out was not read;
  - the vault byte budget skipped frontmatter;
  - a vault mapped by README alone broke on its first capture;
  - plugin-written artifacts were ready by `status` until their loop exited.
- **Round 2 (reviewer `approve`, codex `approve`, security `changes` on minors only).** Fixed in round 2:
  - the frontmatter fence search could be bypassed;
  - safe names accepted a trailing newline;
  - the CLI without `--repo` read settings from the cwd, not the work-tree root;
  - a crash exited 1;
  - `[[README]]` back-links broke after a MOC took over.
- **Round 3 (security `approve`, codex `approve`).** Nits fixed: a README link is excused only by a real file, and
  the `--repo` help text is corrected.

QA: a qa-engineer added 21 end-to-end tests that run the field repros through the shipped entry points as processes.
17 of them fail on master. No defects were found. Gate: `dev/validate.py`, pytest (96.07% coverage), ruff, mypy and
`dev/hook_smoke.py` on Python 3.9.25 all pass.
