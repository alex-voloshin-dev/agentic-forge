# Stage 6 — Design & onboarding domains

Two skills: `ux-design` (UX specs for a feature) and `repo-onboarding` (analyze an unfamiliar
codebase and seed the Stage-3 knowledge vault). Both have their own behavior, so both are
Tier-1 + Tier-2. Built contract-first → evals-first → gate, inspection-gradeable (ADR 0020).
Roadmap: Stage 6. Tier-1 descriptions are written sharp from the start to avoid the keyword
collisions that cost iteration in Stages 4–5 ("design" ↔ architecture, "analyze/research" ↔
research/code-review).

## ux-design

- **Purpose**: turn a feature / PRD into a **UX spec** — user flows, screens and their states
  (empty / loading / error / success), accessibility requirements (WCAG: keyboard, contrast,
  semantics/ARIA), and references to design-system components — handed to `develop`.
- **Own behavior** (there is no UX role to fork); emits a `ux-spec` handoff, gated by a **bounded
  adversarial loop** over two lenses (accessibility + flow/state completeness, ADR 0037) plus the
  external-reviewer lens (`--kind ux`), exiting on the shared `review_loop_decision` (ADR 0061) —
  `escalate` surfaces the gaps instead of handing off.
- **Scope guard** (the roadmap's risk): outputs are **specs and handoff docs, never pixels/visual
  design**. An assertion enforces "spec, not visual mockup".
- **Handoff depth** (ADR 0056): `references/design-handoff.md` carries the per-component
  design-to-code template (token-valued visual spec; variants; ALL states incl. focus/disabled/
  error; ARIA/keyboard/screen-reader) plus the 5-minute accessibility pass — loaded when the spec
  goes to engineering; a Tier-2 case pins the template's non-negotiables (focus/keyboard never
  omitted).
- **Boundary** (avoid the "design" collision): `ux-design` = the *user* experience (flows, screens,
  a11y); `architecture` = the *technical* design (components, decisions, ADRs). The description
  leads with "UX / user flows / screens / accessibility", never bare "design".

## repo-onboarding

- **Purpose**: analyze an **unfamiliar codebase** and **seed the knowledge vault** (Stage 3) — a
  map of components, entry points, conventions, and risks, plus atomic KB notes. Feeds Stage 3.
- **Own behavior**: forks `Explore` to read the code; uses the installed `agentic_forge.vault`
  module to write notes; emits an `onboarding` summary handoff.
- **Boundary**: onboarding an *unfamiliar* codebase + seeding the KB — not feature research
  (`research`), not reviewing a change (`code-review`), not capturing a single decision
  (`knowledge`).

## New handoff types (`handoff.py`, contract-first)

- `ux-spec` — feature schema + `flows` (non-empty), `screens`, `accessibility`, `design_system`.
- `onboarding` — feature schema + `components` (non-empty), `entry_points`, `conventions`, `risks`.

## Eval approach (ADR 0020)

- **Tier-1**: sharp triggers. `ux-design` owns "design the UX / user flow / screens & states /
  accessibility for X" (negatives: technical design → `architecture`, build it → `develop`, the
  PRD → `product`). `repo-onboarding` owns "onboard me to / help me understand this unfamiliar
  codebase / seed the KB from this repo" (negatives: research a feature → `research`, review a
  diff → `code-review`, capture one decision → `knowledge`).
- **Tier-2** (fixture-backed, inspection-gradeable):
  - `ux-design`: a feature → a `ux-spec` covering the key flows, per-screen states
    (empty/error/loading), and concrete a11y requirements, staying spec-level (no pixel/visual
    design).
  - `repo-onboarding`: a small fixture repo → KB notes **grounded in the actual code** (no
    fabricated modules), a valid vault (`validate_vault` clean — linked, no orphans), and an
    `onboarding` map naming the real components/entry points.

## Alternatives considered

- **A UX role for `ux-design` to fork** — none exists; own-behavior is right. Add a `ux` role later
  only if depth warrants (the way the spine added per-domain roles).
- **Fold `repo-onboarding` into `knowledge`** — rejected; `knowledge` is recall/capture of a single
  idea, whereas onboarding is an analyze-a-whole-repo-and-seed workflow. It *uses* the vault lib
  but is its own phase (and feeds Stage 3).

## Exit criteria

- Each skill: Tier-0 green; Tier-1 recall/specificity ≥ 0.9; Tier-2 lower bound ≥ 0.8 (n ≥ 5).
- `repo-onboarding` produces a usable KB seed (valid vault) on a fixture repo.
- `ux-spec` / `onboarding` handoff schemas + tests; docs + an ADR.
