---
name: ux-design
description: Design the UX for a feature — the user flows, the screens and their states (empty / loading / error / success), accessibility requirements (WCAG — keyboard, focus, contrast, ARIA), and design-system component references — as a ux-spec handed to develop. Use to design the user experience / user flows / screens and states / wireframe specs / accessibility for a feature. Not the technical architecture (architecture), implementing it (develop), or the product requirements / PRD (product).
allowed-tools: Read, Grep, Glob, Bash, Task, Write, Edit
---

# UX design (phase workflow)

Turn a feature (or PRD) into a **UX spec**: the user flows, the screens and their states, the
accessibility requirements, and the design-system components to reuse — handed to `develop`. This
is the *user* experience, distinct from `architecture` (the *technical* design). Outputs are
**specs and handoff docs, never pixels** — keep visual/brand design out of scope. (Design:
[ADR 0023](../../../docs/architecture/decisions/0023-stage6-design-onboarding.md),
[design-onboarding.md](../../../docs/architecture/design-onboarding.md).)

## When to use

When the task is to design the user experience for a feature — flows, screens and states, or
accessibility. **Not** the technical architecture (`architecture`), building it (`develop`), or
the product requirements (`product`).

## Process

1. **Read the feature.** Load the feature description / `prd.md`; identify the actors and the jobs
   to be done.
2. **User flows.** Map the key flows (happy path plus the important branches) as step sequences —
   not screens-as-pictures.
3. **Screens and states.** For each screen, specify its states: **empty, loading, error, and
   the populated/success** state — the ones engineers forget. Describe content and behavior, not
   visual layout.
4. **Accessibility.** State concrete WCAG requirements: keyboard navigation and focus order,
   contrast, semantics/ARIA (e.g. live regions for async results), labels for inputs.
5. **Design system.** Reference the components/tokens to reuse (don't invent a visual language).
   When the spec is handed to engineering, load
   [references/design-handoff.md](references/design-handoff.md) — the per-component handoff
   template (tokens, variants, ALL states incl. focus/disabled/error, ARIA/keyboard) and the
   5-minute accessibility pass.
6. **Write the `ux-spec`** with valid YAML frontmatter: `type` (= `ux-spec`), `feature`, `status`,
   and the **list** fields `flows`, `screens`, `accessibility`, `design_system` (each a YAML list —
   not prose; quote any value containing a colon) — as `ux-spec.md` under
   `docs/sdlc/<feature-slug>/`, then validate it
   (`handoff.validate_header(header, expected_type="ux-spec")`) — the input `develop` builds from.
7. **Adversarial review (bounded).** Fork fresh `reviewer`s (via `Task`) on two lenses —
   **accessibility** (keyboard/focus order, contrast, ARIA/live-regions present and correct) and
   **flow/state completeness** (every screen has empty/loading/error/success; no dead-end flow) —
   verify each finding against the spec, then revise worst-first. These are exactly the states and
   a11y items engineers forget. **External reviewer lens (on by default, ADR 0057/0061):** when
   `external_reviewer.enabled` (settings), also run the external reviewer over the spec — call
   `external_review.review(spec_text, "ux", command=<cfg>)` from `${CLAUDE_PLUGIN_ROOT}/lib`
   (repo-side equivalent: `dev/external_review.py --target docs/sdlc/<feature-slug>/ux-spec.md
   --kind ux`); codex critiques it as an independent-model lens over the same two concerns and its
   `findings` fold into the same worst-first revision. It **degrades gracefully** (absent/disabled
   codex is skipped, not a failure) and its findings are **advisory** (prompt-injectable) — verify
   before acting. **Persist each round** — write `docs/sdlc/<feature-slug>/review-<artifact>.md` (`type: review`, `target`, `iteration`, `verdict`, `findings[]`; `dev/external_review.py --out … --iteration N` already emits this shape). Without it the loop leaves no trace and the scheduled non-convergence scan (ADR 0040) cannot see it. **Exit criterion (the shared, tested rule):** each round, aggregate both lenses
   (plus the external one) to a single verdict and compute
   `handoff.review_loop_decision(verdict, iteration, cap=3, gate_green=<the ux-spec validates>)`
   (see [adversarial-review.md](../../patterns/adversarial-review.md), bounded by
   [review-loop.md](../../patterns/review-loop.md)) — `revise` (loop back and fix worst-first),
   `escalate` (still `changes` at N = 3 → **set the artifact's `status` to `in-review`**, surface the unresolved gaps and stop; the status is what makes "don't hand off" enforceable — the file is already on disk), or
   `proceed` (`approve` **and** the spec validates → the spec is done). Don't hand off a spec with a
   dead-end flow or a screen missing its error state.

## Output

**A full ux-design run produces the finished spec: a validated `ux-spec`** — flows, screens +
states, accessibility requirements, and design-system references — that survived the bounded
adversarial loop to `proceed`, ready as the input `develop` builds from. No pixels or visual
mockups — specs only. A run whose loop `escalate`s (unresolved gaps at N = 3) surfaces them and
stops; it does **not** hand off an incomplete spec.

## Definition of done

- The adversarial loop exited on `proceed` (`review_loop_decision`): `approve` **and** the `ux-spec`
  validates — not `escalate`.
- The key user flows and per-screen states (incl. empty + error) are specified.
- Concrete accessibility requirements are stated (keyboard, focus, contrast, ARIA).
- A bounded accessibility + flow-completeness review pass (plus the external-reviewer lens when
  enabled) was run before handoff.
- Output is a spec (a valid `ux-spec` artifact), not a visual/pixel mockup.
