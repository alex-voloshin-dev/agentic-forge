# 0023 — Stage 6: ux-design (specs not pixels) and repo-onboarding (analyze + seed the vault)

Status: Accepted

## Context

Stage 6 is "design & onboarding": `ux-design` and `repo-onboarding`. Open questions (roadmap): how
UI/UX outputs are represented and handed to `develop`, and what `repo-onboarding` extracts and how
it writes to the vault. Risk: UX scope creep into visual design. Design in
[design-onboarding.md](../design-onboarding.md); eval rule per [ADR 0020](0020-tier2-inspection-gradeable-assertions.md).
Tier-1 lessons from Stages 4–5 (keyword collisions cost iteration) are applied up front.

## Decision

- **`ux-design` — own behavior, specs not pixels.** It turns a feature/PRD into a `ux-spec`: user
  flows, screens and their states (empty/loading/error/success), accessibility (WCAG: keyboard,
  focus, contrast, ARIA), and design-system references — handed to `develop`. There is no UX role
  to fork, so it is own-behavior. **Outputs are specs/handoff docs, never pixels** (the scope
  guard, enforced by a Tier-2 assertion). The description leads with "UX / user flows / screens /
  accessibility", never bare "design", to avoid the collision with `architecture` (the *technical*
  design).
- **`repo-onboarding` — analyze + seed the vault.** It forks `Explore` to read an unfamiliar
  codebase, then writes **grounded** atomic notes via the installed `agentic_forge.vault` module
  (Stage 3) and emits an `onboarding` map (components, entry points, conventions, risks). It feeds
  Stage 3; it *uses* the vault lib but is its own analyze-a-whole-repo workflow (distinct from
  `knowledge`'s single-idea recall/capture). Grounding is enforced: every finding points at real
  code, nothing invented.
- **Both are Tier-1 + Tier-2** (own behavior, fixture-backed, inspection-gradeable). `ux-design`'s
  Tier-2 checks flows + per-screen states + concrete a11y, spec-level (no pixels);
  `repo-onboarding`'s checks components/entry-points/risks grounded in a fixture repo and a **valid
  seeded vault** (`validate_vault` clean).
- **New handoff types** `ux-spec` (flows, screens, accessibility, design_system) and `onboarding`
  (components, entry_points, conventions, risks).

## Alternatives considered

- **A UX role for `ux-design` to fork** — none exists; own-behavior is correct. A `ux` role can be
  added later if depth warrants (as the spine grew per-domain roles).
- **Fold `repo-onboarding` into `knowledge`** — rejected; `knowledge` recalls/captures a single
  idea, while onboarding analyzes a whole repo and seeds many linked notes. Shared vault lib, but a
  distinct phase that feeds Stage 3.
- **Rich visual/pixel output for `ux-design`** — rejected (the roadmap risk); specs and handoff
  docs only, so the output is reviewable and feeds `develop`.

## Consequences

- Two skills (`ux-design`, `repo-onboarding`) + two handoff schemas; the listing grows by two.
- `repo-onboarding` ties Stage 6 back to the Stage-3 vault (the KB now has a seeding workflow).
- Real-codebase onboarding depth is the `Explore` role's job behind the existing seam; the gate
  uses a small fixture repo (no live repo needed).

## Exit criteria

- Each skill: Tier-0 green; Tier-1 recall/specificity ≥ 0.9; Tier-2 lower bound ≥ 0.8 (n ≥ 5).
- `repo-onboarding` produces a usable, valid KB seed on the fixture repo.
- `ux-spec` / `onboarding` schemas + tests; docs (this ADR, design-onboarding.md, roadmap,
  overview, CHANGELOG).
