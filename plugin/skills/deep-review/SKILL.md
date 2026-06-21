---
name: deep-review
description: Thorough, adversarial review of a target — docs, design/architecture, a code diff or PR, or the working tree — by fanning out independent reviewers across target-appropriate lenses, verifying every finding against the source, and synthesizing one deduplicated, prioritized report with concrete fixes (optionally applying them and re-running the gate). Use when you want a deep, rigorous, or adversarial review, an audit for contradictions/gaps/bugs/risks, or a second opinion on a non-trivial change. Not for a quick single-pass lint of a tiny diff, running the app, or writing code.
allowed-tools: Read, Grep, Glob, Bash, Edit, Write, Task
---

# Deep review

Run a high-fidelity review that resists single-pass blind spots (especially the author's own).
You orchestrate the [adversarial fan-out pattern](../../patterns/adversarial-review.md):
decompose → fan out independent reviewers → verify findings → synthesize one report.

## When to use

A non-trivial review where completeness and correctness matter: auditing docs or a design for
contradictions/gaps/risks, reviewing a sizeable change set, or an independent second opinion.
**Not** for a quick single-file diff lint (a single `reviewer` pass suffices), running the
app, or writing code.

## Process

1. **Scope the target and pick lenses.** Identify what's being reviewed (docs, design/ADR,
   code diff/PR, or the working tree) and select the relevant lenses from
   [references/lenses.md](references/lenses.md). Each lens is one angle a reviewer focuses on.
2. **Fan out.** Spawn one **fresh, independent** reviewer per lens (the `reviewer` role via a
   forked subagent, or a general-purpose subagent) with *no* prior context, prompted
   **adversarially** ("assume problems exist; hunt them"). Require structured findings: each
   with `severity` (`blocker | major | minor | nit`), `location`, `evidence`, `suggested fix`.
   Run them concurrently with the Task tool (or a Workflow if the user has opted into
   multi-agent orchestration). Scale the count to the ask.
3. **Verify** every substantive finding against the source yourself before accepting it —
   open the file, re-run the check. Drop or downgrade what doesn't hold; keep a note of
   notable false alarms with the reason. This step is non-negotiable: it is what keeps the
   review trustworthy rather than a pile of guesses.
4. **Dedupe & prioritize** across lenses by severity.
5. **Synthesize** one report (see Output). Note clean areas explicitly so silence reads as
   "checked", not "missed".
6. **Apply (only if asked).** Apply the agreed findings, then re-run the relevant gate
   (`python dev/validate.py` + `pytest` for this repo, or the project's gate) and report it.

## Output

A single prioritized report:

- **Findings**, worst-first: `severity` · `location` · what's wrong · concrete fix · (which
  lens / evidence).
- **Filtered** — findings that did not survive verification, with the reason (so the caller
  trusts the rest).
- **Clean** — areas checked and found sound.
- If fixes were applied: what changed and the re-gate result.

## Knobs

- **Breadth/effort** — number of lenses and reviewers; default to the lenses that fit the
  target, expand for "audit everything".
- **Verify rigor** — for high-stakes claims, use multiple independent verifiers and keep a
  finding only if a majority confirm.
- **Apply fixes** — off by default; only when the user asks to fix, not just review.

## Definition of done

- Findings are verified against the source (no unconfirmed speculation presented as fact).
- The report is deduplicated and prioritized; clean areas and filtered false alarms are
  stated.
- If fixes were applied, the gate is green and the numbers/result are reported.
