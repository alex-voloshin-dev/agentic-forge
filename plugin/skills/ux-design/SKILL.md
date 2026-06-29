---
name: ux-design
description: Design the UX for a feature — the user flows, the screens and their states (empty / loading / error / success), accessibility requirements (WCAG — keyboard, focus, contrast, ARIA), and design-system component references — as a ux-spec handed to develop. Use to design the user experience / user flows / screens and states / wireframe specs / accessibility for a feature. Not the technical architecture (architecture), implementing it (develop), or the product requirements / PRD (product).
allowed-tools: Read, Grep, Glob, Task, Write, Edit
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
6. **Write the `ux-spec`** with valid YAML frontmatter: `type` (= `ux-spec`), `feature`, `status`,
   and the **list** fields `flows`, `screens`, `accessibility`, `design_system` (each a YAML list —
   not prose; quote any value containing a colon), then validate it
   (`handoff.validate_header(header, expected_type="ux-spec")`) — the input `develop` builds from.
7. **Adversarial review (bounded).** Fork fresh `reviewer`s (via `Task`) on two lenses —
   **accessibility** (keyboard/focus order, contrast, ARIA/live-regions present and correct) and
   **flow/state completeness** (every screen has empty/loading/error/success; no dead-end flow) —
   verify each finding against the spec, then revise. Bounded, exits on approve (see
   [adversarial-review.md](../../patterns/adversarial-review.md), bounded by
   [review-loop.md](../../patterns/review-loop.md)). These are exactly the states and a11y items
   engineers forget.

## Output

A `ux-spec` handoff: flows, screens + states, accessibility requirements, and design-system
references. No pixels or visual mockups — specs only.

## Definition of done

- The key user flows and per-screen states (incl. empty + error) are specified.
- Concrete accessibility requirements are stated (keyboard, focus, contrast, ARIA).
- A bounded accessibility + flow-completeness review pass was run before handoff.
- Output is a spec (a valid `ux-spec` artifact), not a visual/pixel mockup.
