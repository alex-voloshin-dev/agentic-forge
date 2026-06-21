---
name: code-review
description: Review a CODE change — a diff, a pull request, or the branch from the develop phase — across correctness, security, integration/API, and style/lint, returning an approve/changes verdict with findings and a review.md handoff. Use to review code before merge or as the spine's review phase. For reviewing docs or a design, or a deep adversarial audit, use deep-review; to write code use develop.
allowed-tools: Read, Grep, Glob, Bash(git diff:*), Task, Write
---

# Code review (phase workflow)

The review phase of the SDLC spine: review a code change across aspects and emit a single
verdict + a `review.md` handoff. It is the [multi-aspect review](../../patterns/multi-aspect-review.md)
pattern wired as a skill. Code is its target; **docs/design and deep adversarial audits go to
`deep-review`**.

## When to use

To review a code change — a diff, a PR, or the `develop` phase's output — before it merges, or
as the spine's review step. Not for reviewing docs/design (use `deep-review`), writing code
(`develop`), or designing (`architecture`).

## Process

Follow [multi-aspect-review.md](../../patterns/multi-aspect-review.md):

1. **Scope** the change — `git diff` for the branch/PR, or the diff under review (when invoked
   by `develop`, the worktree diff is supplied to you) — and pick the aspects that apply.
2. **Fan out** one reviewer per aspect (independent, structured findings —
   `severity`, `location`, `issue`, `suggestion`, `evidence`; see
   [patterns/fan-out-fan-in.md](../../patterns/fan-out-fan-in.md)):
   - **correctness / reuse** → [`reviewer`](../../agents/reviewer.md) role;
   - **security** → [`security-engineer`](../../agents/security-engineer.md) role;
   - **integration + API** → `reviewer` (or the relevant stack engineer);
   - **style / lint / warnings** → run the project's real tools (ruff/mypy/eslint/…) and treat
     their output as evidence.
3. **Verify** each finding against the source (open the file, re-run the tool) — drop or
   downgrade what doesn't hold.
4. **Synthesize one verdict.** Aggregate across aspects: **any `blocker`/`major` → `changes`**,
   else `approve`; dedupe, and on a severity conflict keep the highest.
5. **Write the handoff.** Emit `review.md` (`type, target, iteration, verdict, findings[]` —
   see [patterns/handoff.md](../../patterns/handoff.md)); validate it
   (`handoff.validate_header(..., expected_type="review")`).
6. **In the develop loop:** a `changes` verdict loops back to implementation (bounded — see
   [patterns/review-loop.md](../../patterns/review-loop.md)); `approve` proceeds.

## Output

A `review.md` handoff: an `approve`/`changes` verdict plus aspect-organized findings. Read-only
on the code under review — it critiques, it does not edit.

## Definition of done

- One explicit verdict, aggregating all aspects (any blocker/major ⇒ changes).
- Every finding carries severity, location, and a concrete fix; findings verified, not guessed.
- `review.md` validates against the review handoff schema. No code modified.
