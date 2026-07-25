# Pattern: bounded review loop

A writer produces work; the `reviewer` critiques it; the writer revises. Repeat until the
reviewer approves or a budget is exhausted. The loop is **bounded** so it always terminates,
and it **exits early** on approval so it does not waste iterations.

## Participants

- **Writer** — the skill or role that produced the work: the `software-engineer` for code, the
  `architect` for a design, or a workflow skill for an artifact.
- **Reviewer** — the [`reviewer`](../agents/reviewer.md) role, invoked in a forked subagent
  by the orchestrator so it judges in a clean context. It returns a `verdict` (`approve` |
  `changes`) and structured `findings`.
- **Orchestrator** — the workflow skill that owns the loop, the iteration budget, and the
  decision of what to do when the budget runs out.

## The loop

Default budget: **N = 3** iterations. Stop early on `approve`.

```
iteration = 1
approved = False
while iteration <= N:
    review = reviewer(target, criteria)            # forked subagent: verdict + findings
    write review.md (type: review, target, iteration, verdict, findings[])
    if review.verdict == "approve":
        approved = True
        break
    writer.revise(review.findings)                 # address blockers/majors first
    iteration += 1
if not approved:
    escalate(last_review.findings)                 # budget exhausted — see "exit" below
```

Each round writes a `review.md` handoff artifact (see [handoff.md](handoff.md)) with the
`iteration` number and the findings, so the history of the review is auditable.

## Convergence and exit

The exit criterion is one **pure, tested function** so every orchestrator decides identically:
`handoff.review_loop_decision(verdict, iteration, cap=handoff.REVIEW_LOOP_BUDGET, gate_green=…)` →
`proceed` | `revise` | `escalate` (and `handoff.blocks_approve(findings)` is the severity half — a
`blocker`/`major` must force `changes`). `gate_green` is the workflow's downstream gate: QA green for
`develop`; the artifact validating for `product`, `research`, `ux-design` and `architecture` (goals
trace, ADRs weigh real alternatives), and for `plan` also `planning.plan_batches` resolving — no
cycle. It is not always a schema check: `marketing`'s gate is schema validation for a typed handoff
but, for its untyped deliverables (content, offer doc, audit report), the evidence discipline itself
— so there the loop reduces to exit-on-`approve` / `escalate` at N (ADR 0062).

- **Approve → `proceed`** is the success signal (and the loop's *only* exit that hands off) — but
  only when `gate_green`. The reviewer returns `approve` only when no `blocker` or `major` findings
  remain; `minor`/`nit` findings may be left as follow-ups. `approve` with the gate not yet green
  (e.g. QA surfaced a defect) is `revise`, not an exit.
- **Budget exhausted → `escalate`** (still `changes` after N): do **not** silently ship. Escalate =
  persist the final `review.md` (verdict `changes`) and return it to the orchestrating skill,
  which surfaces the unresolved findings to the user and stops — it never auto-merges.
- Address findings worst-first (blocker → major → minor → nit). A revision that only fixes
  nits while a blocker stands will not converge.

## Variations

- **Self-review:** the writer reviews its own work once before the formal loop to catch easy
  issues cheaply; the bounded loop with the independent `reviewer` still follows.
- **Quality-threshold convergence** (grade every iteration with the `grader` instead of an
  approve signal) is possible but costlier; the approve-signal loop is the default (ADR 0009).

## Why bounded

An unbounded loop can oscillate or run forever on a finding the writer cannot resolve. A
fixed budget guarantees termination; the early exit keeps the common case cheap. The cap is a
starting point — a workflow may tune `N` and record why.

See also: [worktree.md](worktree.md) — for code, the reviewer reviews the worktree diff.
