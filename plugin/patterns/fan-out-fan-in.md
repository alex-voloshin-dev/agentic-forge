# Pattern: fan-out / fan-in

Run N **independent** subagents in parallel over a partition of the work, then **synthesize**
their structured results into one. This is the backbone of every Stage 2 phase-workflow:
research parallelises tracks, `develop` reviews by aspect and implements independent plan tasks
in parallel across worktrees (ADR 0034), broad searches sweep several ways at once. The orchestrating skill owns the partition,
the concurrency budget, and the synthesis.

## When to use

- The work splits into pieces that can proceed **without shared mutable state** (research
  directions, code components/services, review aspects, search angles).
- You want breadth or speed, and each piece returns a structured result you can merge.

Do **not** fan out when pieces depend on each other's in-progress state — sequence those, or
fan out only the independent sub-parts.

## The method

1. **Partition** the work into independent units (by direction / component / aspect). State the
   unit list explicitly — it is the contract for the fan-out.
2. **Spawn** one subagent per unit with the `Task` tool (declare `Task` in the skill's
   `allowed-tools` and name the role per unit), each with a focused prompt
   and a **structured return contract** (so results compose) — a minimal unit envelope is
   `{unit, status, result, gaps[]}`; specializations refine `result` (e.g. review findings).
   Run concurrently; cap concurrency to the budget below.
3. **Collect** results; a unit that fails returns empty rather than aborting the batch — keep
   going and record the gap.
4. **Synthesize** into one artifact: merge, dedupe, resolve conflicts, and reconcile
   disagreements between units. Synthesis is a real step, not concatenation.
5. **(Optional) completeness critic** — one pass asking "what's missing — a unit not covered, a
   conflict unresolved?"; its answer seeds another round. Bound the rounds.

## Choosing the subagent type

*(ADR 0073 — field evidence: a fork given a READ-ONLY prompt
opened a real PR.)*

The type is a **containment decision**, not a convenience one — it decides what the child is
allowed to become.

- **Never use `fork` for recon that must not act.** A fork inherits the parent's full context
  *including any standing directive* ("implement this work package"), and an inherited standing
  directive **overrides** a per-call "READ-ONLY, do not edit or commit" prompt. Field evidence: a
  fork given exactly that prompt implemented the change, committed, pushed and opened a real PR.
  For read-only investigation spawn a **fresh** agent (`Explore` / `general-purpose`), which
  inherits nothing. Reserve `fork` for when you genuinely want the child to *continue the
  implementation* with your context.
- **If a subagent must touch files, pass `isolation: "worktree"`** so its edits are contained and
  cannot reach the shared branch or the remote unreviewed (see [worktree.md](worktree.md)).
- **Subagents cannot spawn subagents** (nesting is capped at depth 1). So any *"I reviewed my own
  work with N lenses"* claim coming from a subagent is **false by construction** — it was the
  implementer grading its own diff. Run review lenses at the **top level**, never inside the
  implementing agent.

## Output discipline

*(ADR 0073.)*

A lens can do 40–70 tool calls of real work and still be lost at the **final structured-output
step**: hitting the retry cap kills it outright, or it degenerates into a placeholder finding. The
output-heaviest lenses are the ones that fail — and they are not the redundant ones.

- **Explore deep, emit compact.** Tell each unit: do the exploration with tools, then return a
  *compact* structured result. Cap the findings (~10) and the field lengths (description ≈ 700
  chars, impact ≈ 500, reasoning ≈ 1200) and auxiliary arrays (≈ 4 entries).
- **Scope any regression sweep to that unit's own prior IDs**, not the global set.
- **Health-check the content, not the count.** A unit that returns a placeholder, one generic
  finding, or an empty array *after a long tool run* is **degenerate, not clean** — treat it as
  failed. Counting completed units is not a health check: a degenerate unit still emits
  schema-valid JSON, and the run still reports success.
- **Re-run failed and degenerate units** in a second, smaller run with the same rigor plus the
  caps above. **Do not resume from the prior run id** — resume replays the identical failing
  prompt and schema, and serves the degenerate unit from cache as "done".

## Partitioning rules

- Each unit must be **self-contained**: its inputs are fixed up front, it shares no mutable
  state with siblings.
- For **parallel code** implementation, isolate each unit in its own git worktree (see
  [worktree.md](worktree.md)) so concurrent writers never collide.
- Keep units comparable in size; a unit far larger than the rest becomes the wall-clock floor.

## Bounds & failure

- **Concurrency budget** and **round budget** are owned by the orchestrator and are explicit.
  Sensible defaults: concurrency ≈ 3–5 units in flight and **1 completeness-critic round**;
  tune per phase and record the number (cf. review-loop's `N = 3` convention).
- Partial success is acceptable: surface which units failed and synthesize the rest; never
  present a partial result as complete (state the gaps).

## Composition

- **[multi-aspect-review.md](multi-aspect-review.md)** is fan-out/fan-in specialised to code
  review (one reviewer per aspect → one verdict).
- **[adversarial-review.md](adversarial-review.md)** is the verify-heavy specialisation for
  audits.
- Choosing between them: **multi-aspect** is the code-review gate (fixed aspects, fast, inside
  `develop`); **adversarial** is for non-trivial audits and non-code targets (variable lenses,
  multi-vote verify).
- Each branch may run its own **[review-loop.md](review-loop.md)** and emit a
  **[handoff.md](handoff.md)** artifact; the synthesis step is what turns N branches into the
  one artifact the next phase reads.
