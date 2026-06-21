# Pattern: bounded review loop

A writer produces work; the `reviewer` critiques it; the writer revises. Repeat until the
reviewer approves or a budget is exhausted. The loop is **bounded** so it always terminates,
and it **exits early** on approval so it does not waste iterations.

## Participants

- **Writer** — the skill or role that produced the work: the `implementer` for code, the
  `architect` for a design, or a workflow skill for an artifact.
- **Reviewer** — the [`reviewer`](../agents/reviewer.md) role, run in a fork so it judges in
  a clean context. It returns a `verdict` (`approve` | `changes`) and structured `findings`.
- **Orchestrator** — the workflow skill that owns the loop, the iteration budget, and the
  decision of what to do when the budget runs out.

## The loop

Default budget: **N = 3** iterations. Stop early on `approve`.

```
iteration = 1
while iteration <= N:
    review = reviewer(target, criteria)            # fork: returns verdict + findings
    write review.md (type: review, target, iteration, verdict, findings[])
    if review.verdict == "approve":
        break
    writer.revise(review.findings)                 # address blockers/majors first
    iteration += 1
else:
    escalate(target, last_review.findings)         # budget exhausted, see below
```

Each round writes a `review.md` handoff artifact (see [handoff.md](handoff.md)) with the
`iteration` number and the findings, so the history of the review is auditable.

## Convergence and exit

- **Approve** is the success signal. The reviewer returns `approve` only when no `blocker`
  or `major` findings remain; `minor`/`nit` findings may be left as follow-ups.
- **Budget exhausted** (still `changes` after N): do **not** silently ship. Surface the
  remaining findings to the caller (or the user) and stop. Persisting the last `review.md`
  makes the unresolved items explicit.
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
