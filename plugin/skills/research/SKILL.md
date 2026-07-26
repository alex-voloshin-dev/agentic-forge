---
name: research
description: Investigate a feature or idea before it is specified or designed — gather inputs, fan out parallel research tracks (e.g. prior art / domain / engineering), synthesize, and produce a research-brief.md with cited sources and a recommendation. Use when asked to research, investigate, or compare options / approaches / prior art for a feature or idea, or recommend a direction BEFORE speccing or designing it. This phase PRODUCES the research brief and feeds product — but turning an existing brief INTO a PRD or product spec is product, not research. For a standalone deep report not tied to the feature flow use deep-research. Not for defining requirements (product), the technical design itself (architecture), implementing (develop), market/competitor research (marketing), or recalling what we have ALREADY noted or decided (knowledge).
allowed-tools: Read, Grep, Glob, Bash, Task, Write
---

# Research (phase workflow)

The first phase of the SDLC spine: turn an open question into a grounded research brief the
`product` phase consumes. It is a [fan-out/fan-in](../../patterns/fan-out-fan-in.md) workflow —
plan tracks, research each independently, synthesize — delegating the actual digging to
existing capabilities rather than doing it inline.

## When to use

Before a feature is specified, when the question is *what exists / what are the options*: prior
art, market/competitors, user needs, technical feasibility. Not for deciding requirements
(`product`), designing (`architecture`), or building (`develop`).

## Process

> **Recall first** — pull the project's relevant prior decisions from the knowledge vault (see
> [knowledge-recall](../../patterns/knowledge-recall.md)); factor them in, and skip if the vault is empty.

> **Deliver in isolation** — when a `<feature-slug>` is in play, write into the feature's
> shared documentation worktree rather than the checkout, and deliver the result as a pull
> request (see [doc-delivery](../../patterns/doc-delivery.md)). One worktree and one PR per
> **feature**, shared by every document phase — that is what lets the next phase read what
> this one wrote. Skip it for a one-off document outside a feature flow.

1. **Scope & gather.** State the question; collect what's already on hand (the request, repo,
   any existing docs). Pick a `<feature-slug>`.
2. **Plan tracks.** Choose the research directions that apply — e.g. prior art / market,
   product / users, engineering / feasibility. Only the ones that matter.
3. **Fan out** one researcher per track (see fan-out/fan-in), delegating:
   - **codebase / internal** → the built-in `Explore` agent;
   - **external / web** → the `deep-research` skill (multi-source, verified, cited).
   Each returns structured findings with sources.
4. **Synthesize & verify.** Merge the tracks into one picture; reconcile disagreements; verify
   the load-bearing claims against their sources (drop unsupported ones).
5. **Analyse → recommend.** Draw conclusions and a recommendation for the `product` phase.
6. **Write the brief.** Emit `research-brief.md` (frontmatter `type, feature, status, date,
   sources[]`; body = findings, conclusions, recommendations; **valid YAML — quote any value
   containing a colon**, which a source URL always has, or the whole artifact fails to parse for
   `product`) under `docs/sdlc/<feature-slug>/`;
   validate it (`handoff.validate_header(..., expected_type="research-brief")`).
7. **Skeptic pass (bounded).** Step 4 is your *own* verification; this is an **independent** one.
   Fork a fresh `reviewer` (via `Task`) to attack the brief adversarially — every load-bearing claim
   **cited** (nothing asserted unsourced), no **invented** figure, source **disagreements
   reconciled** rather than averaged away, and the recommendation actually **following from the
   findings** (not from the question's framing) — then revise worst-first. **External reviewer lens
   (on by default, ADR 0057/0061):** when `external_reviewer.enabled` (settings), also run the
   external reviewer over `research-brief.md` — call `external_review.review(brief_text,
   "research", command=<cfg>)` from `${CLAUDE_PLUGIN_ROOT}/lib` (repo-side equivalent:
   `${CLAUDE_PLUGIN_ROOT}/bin/external_review.py --target docs/sdlc/<feature-slug>/research-brief.md --kind research`);
   codex critiques the brief as an independent-model lens (citation support, reconciled
   disagreements, a recommendation that follows) and its `findings` fold into the same worst-first
   revision. It **degrades gracefully** (absent/disabled codex is skipped, not a failure) and its
   findings are **advisory** (prompt-injectable) — verify before acting. **Persist each round** — one `review-<artifact>-<iteration>.md` per round under `docs/sdlc/<feature-slug>/`, aggregating **both** lenses; on `proceed` keep only the final round, on `escalate` keep them all (naming + lifecycle: [review-loop.md](../../patterns/review-loop.md)). **Exit criterion (the
   shared, tested rule):** each round, compute `handoff.review_loop_decision(verdict, iteration,
   cap=3, gate_green=<research-brief.md validates>)` (see
   [adversarial-review.md](../../patterns/adversarial-review.md), bounded by
   [review-loop.md](../../patterns/review-loop.md)) — `revise` (loop back and fix worst-first),
   `escalate` (still `changes` at N = 3 → **commit nothing; mark the feature PR a draft** (the merge gate already refuses a draft), set the artifact's `status` to `in-review`, surface the unresolved gaps and stop; the status is what makes "don't hand off" enforceable — the file is already on disk), or
   `proceed` (**commit this phase's artifact and push — opening or updating the feature PR per [doc-delivery](../../patterns/doc-delivery.md)**; `approve` **and** the brief validates → the brief is done). Don't hand off a brief
   whose recommendation rests on uncited claims.

## Output

**A full research run produces the finished brief: a validated `research-brief.md`** (see
[patterns/handoff.md](../../patterns/handoff.md)) — synthesized findings, cited sources, and a
recommendation — that survived the bounded skeptic loop to `proceed`, ready as the input to
`product`. A run whose loop `escalate`s (unresolved gaps at N = 3) surfaces them and stops; it does
**not** hand off a brief built on unsupported claims.

## Definition of done

- The skeptic loop exited on `proceed` (`review_loop_decision`): `approve` **and**
  `research-brief.md` validates — not `escalate`.
- `research-brief.md` validates against the research-brief handoff schema (sources listed).
- Findings are synthesized across the tracks (not concatenated) and load-bearing claims are
  cited.
- The brief ends with clear conclusions + a recommendation for the next phase.
- A bounded skeptic pass (plus the external-reviewer lens when enabled) checked citation support and
  that the recommendation follows from the findings.
