---
name: architecture
description: Turn an approved product spec (a PRD) into a TECHNICAL design — components, key decisions captured as ADRs, and risks — written to docs/sdlc/<feature>/. Use when asked to design the architecture or technical approach for a feature or module, decide how to build it, produce or write a tech design, or write an ADR. This is the design (the *how*) — not building the feature (that's develop), defining product requirements (product), or task breakdown (plan).
allowed-tools: Read, Grep, Glob, Write, Task
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

1. **Read the inputs.** Load the `prd.md` handoff (`docs/sdlc/<feature-slug>/prd.md`) — use
   `agentic_forge.handoff.load_artifact(..., expected_type="prd")` — and study how the current
   system is built so the design fits reality.
2. **Find the decisions that matter.** Identify the few choices that shape the design
   (datastore, boundaries, sync model, …). When several are independent, evaluate them in
   parallel (fan out — see [patterns/fan-out-fan-in.md](../../patterns/fan-out-fan-in.md)) and
   synthesize.
3. **Weigh real alternatives** for each decision; honor stated constraints (a constraint that
   forces a trade-off becomes a risk).
4. **Delegate the write-up** to the `architect` role (fork via the `Task` tool): it produces
   `tech-design.md` (frontmatter `type`, `feature`, `status`, `decisions`, `components`, `risks`) plus one `adr-*.md` per
   decision (Context, Decision, Alternatives considered, Consequences), under
   `docs/sdlc/<feature-slug>/`.
5. **Validate the handoff.** Confirm `tech-design.md` validates against its schema
   (`handoff.validate_header(..., expected_type="tech-design")`), every PRD goal traces to a
   component or an explicit decision, and each ADR records a genuinely rejected alternative.
6. **(Optional) review pass.** For a non-trivial design, run a bounded review loop with the
   `reviewer` role or `deep-review` (see [patterns/review-loop.md](../../patterns/review-loop.md))
   before handing off.

## Output

Handoff artifacts under `docs/sdlc/<feature-slug>/`: `tech-design.md` + `adr-*.md` (see
[patterns/handoff.md](../../patterns/handoff.md)). These are what `plan` and `develop` read.

## Definition of done

- `tech-design.md` validates against the `tech-design` handoff schema (decisions, components,
  risks present).
- Every PRD goal maps to a component or an explicit decision.
- Each significant decision is an ADR weighing real alternatives with consequences.
- Only design documents are written — no application code.
