# 0015 — By-stack: deterministic detection helper + stack reference packs

Status: Accepted

## Context

ADR 0014 decided *that* stack specialization lives in skills (one `software-engineer` base
role that loads a lean `engineering-standards` skill plus a stack `*-patterns` skill), not in
per-stack agents, and that the concrete mechanism arrives in the **by-stack step** after the
Python thin slice. The thin slice is now built and proven end-to-end (Tier-3), but every phase
is still implicitly Python: `develop` and `code-review` name `pytest`/`ruff`/`mypy` directly,
there is no way to *know* a target repo's stack, and no `*-patterns` pack exists. This ADR pins
down the by-stack mechanism so the spine works on any stack and grows to new languages by
adding data, not executors.

Two forces shape the decision:

- **Determinism over guessing.** Which stack a repo is and which commands to run is a fact in
  the repo (manifests, declared scripts), not a judgment call. A wrong guess silently runs the
  wrong test/lint command and corrupts the review gate. So detection must be a tested,
  deterministic helper in `lib/`, not prose the model improvises.
- **Router discipline.** Stack packs must not consume the always-on skill-listing budget
  (ADR 0004). They are off-listing knowledge loaded on demand for the detected stack.

## Decision

- **Deterministic detection helper `lib/agentic_forge/stacks.py`.** `detect(repo) -> list[
  StackProfile]` identifies a target repo's stack(s) from evidence, ranked, with a convenience
  `primary(repo)`. Precedence: (1) an explicit `stack:` hint in the repo's `CLAUDE.md` /
  `AGENTS.md`; (2) known manifest signatures (`pyproject.toml`/`setup.py`/… → python;
  `tsconfig.json` (+`package.json`) → typescript, bare `package.json` → javascript;
  `go.mod` → go; `Cargo.toml` → rust; `pom.xml`/`build.gradle` → jvm; `*.csproj`/`*.sln` →
  dotnet; `Gemfile` → ruby; `composer.json` → php). An empty/unknown repo yields the `unknown`
  profile (engineering-standards only).
- **A `StackProfile` is the "stack profile" input** the workflows take (as foreseen in
  spine.md): `stack_id`, `display`, `pack` (the `*-patterns` skill name or `None`),
  `toolchain` (conventional `test`/`lint`/`typecheck`/`format` commands), and the `manifests`
  found (evidence). Commands in the profile are **conventional fallbacks** — the consumer
  always prefers the repo's own declared commands (CLAUDE.md / Makefile / `package.json`
  scripts) when present.
- **A registry `STACKS` carries data, not code.** Adding a language = one registry entry
  (manifest globs + toolchain defaults + optional pack name). Detection ships for the common
  stacks above immediately; **knowledge packs ship incrementally.**
- **`python-patterns` is the first stack pack.** An off-listing
  (`disable-model-invocation: true`) `*-patterns` knowledge skill modelled on
  `engineering-standards`: the Python toolchain (and how to find the repo's real commands),
  idioms, testing conventions, layout, and pitfalls. Its `evals.json` declares a
  `tier2_quality` readiness contract (no `tier1_trigger` — it is not auto-triggered),
  **exercised through `software-engineer`'s Tier-2**, like `engineering-standards` (see the
  eval-runbook scope note; no automated skill-Tier-2 CLI yet).
- **Detection-without-a-pack falls back, explicitly.** A detected stack whose `pack` is `None`
  (typescript/go/rust/… today) runs under `engineering-standards` + the profile's toolchain
  defaults. This is honest, not silent: the workflow logs the detected stack and that no pack
  was loaded. New packs are a follow-on, one `*-patterns` skill at a time.
- **Wiring.** `develop` gains an explicit "detect the stack → load the pack (or fall back) →
  use the stack's commands" step; `code-review`'s style/lint aspect runs the detected stack's
  real tools (preferring repo-declared commands); the `software-engineer` and `qa-engineer`
  roles load the detected `*-patterns` pack alongside `engineering-standards`.

## Alternatives considered

- **LLM-only stack detection** (ask the model to infer the stack/commands): rejected — a wrong
  inference silently runs the wrong gate. Detection is a fact; make it deterministic and tested.
- **Per-stack agents** (`python-engineer`, `frontend-engineer`, …): already rejected in
  ADR 0014; restated here because the registry could have been keyed to agents. Stack idioms
  are data (packs), not executors.
- **Ship all stack packs now**: rejected — each pack's quality must be exercised (Tier-2
  through the role) and non-Python toolchains are environment-fragile in the eval sandbox.
  Detection (cheap, deterministic) ships broad; packs (expensive, judged) ship one at a time.
- **Hardcode commands in the workflow skills**: rejected — that is exactly the Python coupling
  we are removing; commands belong in the registry as data, overridable by the repo.

## Consequences

- The spine is stack-parametric: detection works for the common stacks immediately; Python has
  a full pack; other stacks run on standards + toolchain defaults until their pack ships.
- `stacks.py` is unit-tested (manifest fixtures + override precedence + fallback), keeping
  Tier-0 coverage ≥ 80%; it is the single source of truth for "what stack + what commands".
- Adding a language later is additive: a registry entry (detection) and, when warranted, a
  `*-patterns` pack (knowledge) — no new agents, no listing-budget cost.
- `*-patterns` packs join `engineering-standards`/`deep-review`/`skill-factory` as skills that
  declare `tier2_quality` as a readiness contract run via the harness / role Tier-2, not an
  automated skill-Tier-2 gate (eval-runbook scope note).
- This completes the Stage 2 by-stack item; it builds on ADR 0014 (does not supersede it).
