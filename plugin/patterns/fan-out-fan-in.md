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
