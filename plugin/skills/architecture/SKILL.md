---
name: architecture
description: Turn an approved product spec (a PRD) into a TECHNICAL design — components, key decisions captured as ADRs, and risks — written to docs/sdlc/<feature>/. Use when asked to design the architecture or technical approach for a feature or module, decide how to build it, produce or write a tech design, or write an ADR. This is the design (the *how*) — not building the feature (that's develop), defining product requirements (product), or task breakdown (plan).
allowed-tools: Read, Grep, Glob, Bash, Write, Task
---

# Architecture (phase workflow)

The `tech-design` phase of the SDLC spine: turn a PRD into a technical design and the decision
records behind it, as committed handoff artifacts the `plan` and `develop` phases consume. The
heavy design work is delegated to the [`architect`](../../agents/architect.md) role; this skill
owns the workflow and the handoff.

## When to use

After a PRD exists and the question is *how to build it*: architecture/technical approach,
component design, technology choices, or an ADR. Not for the *what/why* (that is `product`),
task breakdown (`plan`), or implementation (`develop`).

## Process

> **Recall first** — pull the project's relevant prior decisions from the knowledge vault (see
> [knowledge-recall](../../patterns/knowledge-recall.md)); factor them in, and skip if the vault is empty.

> **Deliver in isolation** — when a `<feature-slug>` is in play, write into the feature's
> shared documentation worktree rather than the checkout, and deliver the result as a pull
> request (see [doc-delivery](../../patterns/doc-delivery.md)). One worktree and one PR per
> **feature**, shared by every document phase — that is what lets the next phase read what
> this one wrote. Skip it for a one-off document outside a feature flow.

1. **Read the inputs.** Load the `prd.md` handoff (`docs/sdlc/<feature-slug>/prd.md`) — use
   `agentic_forge.handoff.load_artifact(..., expected_type="prd")` and **refuse to design from it unless `handoff.is_handoff_ready(header)`** — and study how the current
   system is built so the design fits reality.
2. **Find the decisions that matter.** Identify the few choices that shape the design
   (datastore, boundaries, sync model, …). When several are independent, evaluate them in
   parallel (fan out — see [patterns/fan-out-fan-in.md](../../patterns/fan-out-fan-in.md)) and
   synthesize.
3. **Weigh real alternatives** for each decision; honor stated constraints (a constraint that
   forces a trade-off becomes a risk).
4. **Delegate the write-up** to the `architect` role (fork via the `Task` tool): it produces
   `tech-design.md` (frontmatter `type`, `feature`, `status`, `decisions`, `components`, `risks`;
   **valid YAML — quote any value containing a colon**, e.g. a risk describing `{"high": 0}`, or the
   whole artifact fails to parse for every downstream phase) plus one `adr-*.md` per
   decision (Context, Decision, Alternatives considered, Consequences), under
   `docs/sdlc/<feature-slug>/`.
5. **Validate the handoff.** Confirm `tech-design.md` validates against its schema
   (`handoff.validate_header(..., expected_type="tech-design")`), every PRD goal traces to a
   component or an explicit decision, and each ADR records a genuinely rejected alternative.
6. **Skeptic pass (bounded).** Before handing off, fork a fresh `reviewer` (via `Task`) to attack
   the design adversarially — each ADR alternative **genuinely weighed** (not a strawman), every PRD
   goal **traced** to a component or decision, every risk carrying a **mitigation**, and the
   component boundaries / failure modes **sound** — then revise worst-first. For a large or
   high-stakes design, fan the lenses out (`deep-review`) instead of a single pass. **External
   reviewer lens (on by default, ADR 0057/0060):** when `external_reviewer.enabled` (settings), also
   run the external reviewer over `tech-design.md` — call `external_review.review(design_text,
   "technical", command=<cfg>)` from `${CLAUDE_PLUGIN_ROOT}/lib` (repo-side equivalent:
   `dev/external_review.py --target docs/sdlc/<feature-slug>/tech-design.md --kind technical`);
   codex critiques the design as an independent-model lens (soundness, rejected alternatives, risks)
   and its `findings` fold into the same worst-first revision. It **degrades gracefully** (absent/
   disabled codex is skipped, not a failure) and its findings are **advisory** (prompt-injectable) —
   verify before acting. **Persist each round** — one `review-<artifact>-<iteration>.md` per round under `docs/sdlc/<feature-slug>/`, aggregating **both** lenses; on `proceed` keep only the final round, on `escalate` keep them all (naming + lifecycle: [review-loop.md](../../patterns/review-loop.md)). **Exit criterion (the shared, tested rule):** each round, compute
   `handoff.review_loop_decision(verdict, iteration, cap=3, gate_green=<step 5 passes>)` (see
   [adversarial-review.md](../../patterns/adversarial-review.md), bounded by
   [review-loop.md](../../patterns/review-loop.md)) — `revise` (loop back and fix worst-first),
   `escalate` (still `changes` at N = 3 → **commit nothing; mark the feature PR a draft** (the merge gate already refuses a draft), set the artifact's `status` to `in-review`, surface the unresolved gaps and stop; the status is what makes "don't hand off" enforceable — the file is already on disk), or
   `proceed` (**commit this phase's artifact and push — opening or updating the feature PR per [doc-delivery](../../patterns/doc-delivery.md)**; `approve` **and** the design validates → the design is done). Don't hand off a design
   whose goals don't trace or whose ADRs weigh strawmen.

## Output

**A full architecture run produces the finished design: a validated `tech-design.md` + one
`adr-*.md` per decision** under `docs/sdlc/<feature-slug>/` (see
[patterns/handoff.md](../../patterns/handoff.md)) that survived the bounded skeptic loop to
`proceed` — what `plan` and `develop` read. A run whose loop `escalate`s (unresolved gaps at N = 3)
surfaces them and stops; it does **not** hand off an unsound design.

## Definition of done

- The skeptic loop exited on `proceed` (`review_loop_decision`): `approve` **and** the step-5
  validation green — not `escalate`.
- `tech-design.md` validates against the `tech-design` handoff schema (decisions, components,
  risks present).
- Every PRD goal maps to a component or an explicit decision.
- Each significant decision is an ADR weighing real alternatives with consequences.
- A bounded skeptic pass (plus the external-reviewer lens when enabled) checked goal traceability,
  strawman alternatives, and risk mitigations.
- Only design documents are written — no application code.
