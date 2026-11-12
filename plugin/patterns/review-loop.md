# Pattern: bounded review loop

`${CLAUDE_PLUGIN_ROOT}` below is the plugin's directory, the one holding `skills/` and `patterns/`, and is not normally set in a shell: if this file reached you unexpanded, use the path your skill's own commands show.

A writer produces work; the `reviewer` critiques it; the writer revises. Repeat until the
reviewer approves or a budget is exhausted. The loop is **bounded** so it always terminates,
and it **exits early** on approval so it does not waste iterations.

## Participants

- **Writer** — the skill or role that produced the work: the `software-engineer` for code, the
  `architect` for a design, or a workflow skill for an artifact.
- **Reviewer** — the [`reviewer`](../agents/reviewer.md) role, invoked in a fresh subagent (never
  the `fork` type, which would inherit the author's context — see
  [fan-out-fan-in.md](fan-out-fan-in.md#choosing-the-subagent-type))
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
    review = reviewer(target, criteria)            # fresh subagent: verdict + findings
    write review.md (type: review, target, iteration, verdict, findings[])
    if review.verdict == "approve":
        approved = True
        break
    writer.revise(review.findings)                 # address blockers/majors first
    iteration += 1
if not approved:
    escalate(last_review.findings)                 # budget exhausted — see "exit" below
```

## Persisting the loop (ADR 0071)

Each round writes **one** review artifact — `review-<artifact>-<iteration>.md` under
`docs/sdlc/<feature-slug>/` (`type: review`, `target`, `iteration`, `verdict`, `findings[]`; see
[handoff.md](handoff.md)).

Three rules, because getting any of them wrong litters the user's repository:

1. **The iteration is in the FILENAME, not only the frontmatter.** A single fixed name cannot hold a
   history — writing it every round overwrites the previous one — so a fixed name and "the history
   is auditable" are incompatible asks. Indexing the name resolves it without the writer inventing
   a convention.
2. **One artifact per round, aggregating every lens.** The internal reviewer and the external
   reviewer both run in a round; their verdicts are already aggregated into the one verdict the exit
   rule consumes, so their findings belong in one file too. Writing a separate file per lens
   multiplies the output by the number of lenses for no gain.
3. **Lifecycle.** On `escalate` **keep every round** — they are the evidence for the unresolved
   findings, and the non-convergence scan (ADR 0040) reads them. On `proceed` keep only the **final**
   round (the one recording the `approve`) and delete the earlier ones: they gate nothing, the scan
   can never flag a converged loop, and leaving them means handing the user files they did not ask
   for.

## Convergence and exit

The exit criterion is one **pure, tested function** so every orchestrator decides identically:
`python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" review-decision --verdict <verdict> --iteration <n> --gate-green <yes, no or unknown>` →
`proceed` | `revise` | `escalate` (and `python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" review-blocks --findings-json <file>` is the severity half — a
`blocker`/`major` must force `changes`). `unknown` is a gate that could not be run (`handoff-load` exited 3) and always escalates. The gate is the workflow's downstream gate: QA green for
`develop`; the artifact validating for `product`, `research`, `ux-design` and `architecture` (goals
trace, ADRs weigh real alternatives), and for `plan` also `plan-batches` resolving — no
cycle. It is not always a schema check: `marketing`'s gate is schema validation for a typed handoff
but, for its untyped deliverables (content, offer doc, audit report), the evidence discipline itself
— so there the loop reduces to exit-on-`approve` / `escalate` at N (ADR 0062).

- **Approve → `proceed`** is the success signal (and the loop's *only* exit that hands off) — but
  only when the gate is `yes`. The reviewer returns `approve` only when no `blocker` or `major` findings
  remain; `minor`/`nit` findings may be left as follow-ups. `approve` with the gate not yet green
  (e.g. QA surfaced a defect) is `revise`, not an exit, until the budget runs out.
- **On `proceed`, set the artifact's `review_decision` to `proceed` and run `handoff-load` again
  before staging it.** Without the field, `ready` falls back to `status`, which may say `draft` (or
  whatever lifecycle label the repository uses), so the next phase would reject the artifact this
  loop just passed. Leave `status` alone: it is the repository's field, not the loop's
  ([handoff.md](handoff.md) has the readiness table).
- **Budget exhausted → `escalate`** (still `changes` after N, or a gate still red after N): do **not**
  silently ship. Escalate =
  persist the final `review.md` (verdict `changes`), set the artifact's `review_decision` to
  `escalate` (it wins over any `status`, so the next phase refuses the artifact), and return it to
  the orchestrating skill, which surfaces the unresolved findings to the user and stops — it never
  auto-merges.
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
