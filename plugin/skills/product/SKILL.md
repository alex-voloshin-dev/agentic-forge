---
name: product
description: Produce PRODUCT REQUIREMENTS from research — take an existing research brief and turn it INTO a PRD / product spec (goals, non-goals, success metrics, acceptance criteria) with user stories, and assess the current product. Use to write a PRD, define requirements / goals / acceptance criteria, specify what to build, write user stories, or turn a research brief INTO a product spec. The brief is an INPUT that already exists — producing it is research; this is the speccing step that consumes it. Not the technical design (architecture), task planning (plan), implementing (develop), or market/competitor analysis and offer/pricing design (marketing).
allowed-tools: Read, Grep, Glob, Task, Write
---

# Product (phase workflow)

The product phase of the SDLC spine: decide *what to build and why*, turning a research brief
into a PRD the `architecture` phase consumes. This is the conversational phase — elicit what's
missing from the user rather than inventing it.

## When to use

After research, when the question is *what & why*: goals, non-goals, success metrics,
acceptance criteria, user stories. Not for *what exists* (`research`), *how to build it*
(`architecture`), task breakdown (`plan`), or code (`develop`).

## Process

> **Recall first** — pull the project's relevant prior decisions from the knowledge vault (see
> [knowledge-recall](../../patterns/knowledge-recall.md)); factor them in, and skip if the vault is empty.

1. **Digest the inputs.** Load `research-brief.md`
   (`handoff.load_artifact(..., expected_type="research-brief")`) and assess the current product
   (repo, existing docs). Pick the `<feature-slug>`.
2. **Frame the change.** From the brief's findings + recommendation, decide the **goals** and
   the explicit **non-goals** (what's out of scope), and the **success metrics**. When the ask
   involves ordering the work (what to build next, MVP scope, roadmap) or picking the metrics,
   load [references/prioritization.md](references/prioritization.md) — the framework-selection
   table (RICE / ICE / MoSCoW / JTBD / Kano), the metric frameworks, and the roadmap shape.
3. **User stories.** Write the change as user stories (from the user's perspective), each with
   acceptance criteria.
4. **Acceptance.** Turn the stories into concrete, testable **acceptance criteria** for the
   feature. Elicit anything ambiguous from the user — don't guess load-bearing decisions.
5. **Write the PRD.** Produce `prd.md` (frontmatter `type`, `feature`, `status`, `goals`, `non_goals`, `metrics`,
   `acceptance`; body = context + user stories) under `docs/sdlc/<feature-slug>/`; validate it
   (`handoff.validate_header(..., expected_type="prd")`). Keep every requirement traceable to
   the brief.
6. **Skeptic pass (bounded).** Before handing off, fork a fresh `reviewer` (via `Task`) to
   challenge the draft adversarially — every acceptance criterion **testable**, every success
   metric **measurable**, the **non-goals complete**, and each requirement **traceable to the
   brief** — then revise worst-first. **External reviewer lens (on by default, ADR 0057):** when
   `external_reviewer.enabled` (settings), also run the external reviewer over `prd.md` — call
   `external_review.review(prd_text, "product", command=<cfg>)` from `${CLAUDE_PLUGIN_ROOT}/lib`
   (repo-side equivalent: `dev/external_review.py --target docs/sdlc/<feature-slug>/prd.md --kind
   product`); codex critiques the PRD as an
   independent-model lens (testable criteria, measurable metrics, complete non-goals, traceability)
   and its `findings` fold into the same worst-first revision. It **degrades gracefully** (absent/
   disabled codex is skipped, not a failure) and its findings are **advisory** (prompt-injectable) —
   verify before acting. **Exit criterion (the shared, tested rule):** each round, compute
   `handoff.review_loop_decision(verdict, iteration, cap=3, gate_green=<prd.md validates>)` (see
   [adversarial-review.md](../../patterns/adversarial-review.md), bounded by
   [review-loop.md](../../patterns/review-loop.md)) — `revise` (loop back and fix worst-first),
   `escalate` (still `changes` at N = 3 → surface the unresolved gaps and stop; don't hand off), or
   `proceed` (`approve` **and** the PRD validates → the doc is done). Don't hand off a PRD with
   untestable acceptance criteria.

## Output

**A full product run produces the finished feature documentation: a complete, validated `prd.md`**
(see [patterns/handoff.md](../../patterns/handoff.md)) — goals, non-goals, metrics, testable
acceptance, and user stories — that survived the bounded skeptic loop to `proceed`, ready as the
input to `architecture`. A run whose loop `escalate`s (unresolved gaps at N = 3) surfaces them and
stops; it does **not** hand off an incomplete PRD.

## Definition of done

- The skeptic loop exited on `proceed` (`review_loop_decision`): `approve` **and** `prd.md`
  validates — not `escalate`.
- `prd.md` validates against the prd handoff schema (goals + acceptance present).
- Non-goals and success metrics are stated; user stories cover the goals.
- Requirements trace to the research brief; ambiguities were elicited, not invented.
- A bounded skeptic pass checked acceptance-criteria testability and metric measurability.
- Only product requirements — no technical design or code.
