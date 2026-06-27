---
name: product
description: Produce PRODUCT REQUIREMENTS from research — take an existing research brief and turn it INTO a PRD / product spec (goals, non-goals, success metrics, acceptance criteria) with user stories, and assess the current product. Use to write a PRD, define requirements / goals / acceptance criteria, specify what to build, write user stories, or turn a research brief INTO a product spec. The brief is an INPUT that already exists — producing it is research; this is the speccing step that consumes it. Not the technical design (architecture), task planning (plan), or implementing (develop).
allowed-tools: Read, Grep, Glob, Write
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

1. **Digest the inputs.** Load `research-brief.md`
   (`handoff.load_artifact(..., expected_type="research-brief")`) and assess the current product
   (repo, existing docs). Pick the `<feature-slug>`.
2. **Frame the change.** From the brief's findings + recommendation, decide the **goals** and
   the explicit **non-goals** (what's out of scope), and the **success metrics**.
3. **User stories.** Write the change as user stories (from the user's perspective), each with
   acceptance criteria.
4. **Acceptance.** Turn the stories into concrete, testable **acceptance criteria** for the
   feature. Elicit anything ambiguous from the user — don't guess load-bearing decisions.
5. **Write the PRD.** Produce `prd.md` (frontmatter `goals`, `non_goals`, `metrics`,
   `acceptance`; body = context + user stories) under `docs/sdlc/<feature-slug>/`; validate it
   (`handoff.validate_header(..., expected_type="prd")`). Keep every requirement traceable to
   the brief.

## Output

A `prd.md` handoff (see [patterns/handoff.md](../../patterns/handoff.md)): goals, non-goals,
metrics, acceptance, and user stories — the input to `architecture`.

## Definition of done

- `prd.md` validates against the prd handoff schema (goals + acceptance present).
- Non-goals and success metrics are stated; user stories cover the goals.
- Requirements trace to the research brief; ambiguities were elicited, not invented.
- Only product requirements — no technical design or code.
