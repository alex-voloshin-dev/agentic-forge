---
type: release
feature: agentic-forge-2026.11.13
status: final
version: 2026.11.13
date: 2026-11-23
changelog:
  - "A handoff artifact may open with one '# Title' line, then its '---' header; handoff-load, plan-batches and artifact-home accept it (ADR 0112)."
  - "Skill and agent frontmatter and the vault stay strictly header-first; the opt-in is frontmatter.parse(allow_title=True), used only for handoff artifacts."
breaking: []
---
# Release 2026.11.13

One change from the field queue: board `known-issues` item 8, reported in thread 64a85c8a. ADR 0112 records the
decision.

## What changed

- **A handoff artifact may open with a title.**
  - **Before:** `frontmatter.parse` required the `---` header to open the file. A documentation repository whose CI
    requires every document to start with `# Title` refused the plugin's own artifacts in its feature folder:
    `af.py handoff-load` failed and `af.py artifact-home` reported `format: foreign`.
  - **Now:** one `# Title` line, with blank lines around it, may come before the header. `handoff-load`,
    `plan-batches`, `diagnostics`, the Tier-3 spine checks and `artifact-home`'s format probe accept it. The title
    stays the first line of the body.
- **Still refused:** a title with no header, two H1 lines, an H2, `#Title` without the space, an empty title
  (`# #`), prose or a BOM before the header.
- **Unchanged:** skill and agent frontmatter, the eval runners, the pre-router and the vault stay strictly
  header-first. Header-first stays the default for handoffs; the title-first form is for repositories that require a
  leading title (`plugin/patterns/handoff.md`).
- **Declined:** a sidecar metadata file. Header and body are one reviewed unit, and two files drift.

## How it was checked

- One review round: reviewer, security-engineer and the external lens (codex), all approve. The reviewer's minor
  findings (amend-mode docs, the order wording, CommonMark rendering note, an agreement test, `# #` as an empty
  title, CHANGELOG section) were applied after the round.
- QA: an end-to-end field repro (title-first PRD and plan in a repository feature folder, through `artifact-home`,
  the printed `handoff_load` command and `plan-batches`), strict-caller tests for skills, agents, the pre-router and
  the vault, and a source scan that only the handoff parser opts in. The repro fails on 2026.11.12. A 2,816-input
  fuzz found no disagreement between the format probe and the parser.
- Tier-0: `dev/validate.py`, `ruff`, `mypy` (including `plugin/bin`), the full pytest suite (5,941 passed, 96 %
  coverage), and `dev/hook_smoke.py` under Python 3.9.25.

## Not validated

No skill description or role changed, so per the eval policy this release ran Tier-0 and the direct tests only.

- Tier-1 (trigger), Tier-1b (activation): not run.
- Tier-2 (quality): not run. Whether a model keeps the title line first when it edits `review_decision` in a
  title-first file is checked by no code; only a Tier-2/3 run would show it.
- Tier-3 (E2E spine): not run.

## Known limits (ADR 0112)

- In the title-first form no Markdown renderer shows the header as frontmatter; under CommonMark the YAML renders
  as a heading, which a heading-based linter or index may see.
- An indented title, or a title of only non-breaking spaces, is refused (loudly).
