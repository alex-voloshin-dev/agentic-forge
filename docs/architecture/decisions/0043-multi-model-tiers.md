# 0043 — Multi-model support (tier by task complexity)

Status: Accepted — **implemented** (planned-increment 4; see the [Unreleased] CHANGELOG entry).

## Context

Planned-increment 4: the plugin should use cheaper models (sonnet / haiku) for simpler work and the
strongest (opus) for hard work — e.g. routing / grading / recall / simple synthesis on a cheap tier,
implementation / design / security / adversarial review on the default tier. The `model` frontmatter
field exists and the eval runners take `--model`, but tiering is not a deliberate, configurable
policy. `settings.models` (increment 3) is the config surface, inert until now.

**Constraint that shapes the whole design:** Tier-1 and Tier-2 are **model-dependent**. A cheaper
model is only valid for a component if that component still passes its gate at that tier. So the
default must **not** silently downgrade (that would ship an un-validated quality regression);
tiering is **opt-in and gate-validated**.

## Decision

1. **A tier resolver, `lib/agentic_forge/models.py`.** Built-in `TIERS` maps tier names to model
   ids (`default` → opus-4-8, `simple` → sonnet-4-6, `cheap` → haiku-4-5). `model_for(component,
   models, *, default)` resolves the model for a component: a per-component entry in
   `settings.models` wins — its value is a **tier name** (→ that tier's model) or a **model id**
   (used as-is) — otherwise the global `default` (the runner's `--model`). Pure + tested.

2. **Safe defaults — no downgrade out of the box.** With an empty `settings.models` (the default),
   every component resolves to the global default (opus today): current, validated behaviour is
   unchanged. Tiering is opt-in, e.g. `"models": {"grader": "simple", "router": "cheap"}`.

3. **The eval runners resolve per-component, and the gates enforce the tier.** `run_agent_evals` /
   `run_skill_evals` / `run_tier1_evals` compute `model_for(component, settings.models,
   default=--model)` per role / skill / router and run that component at that tier. So configuring a
   cheaper tier is **validated by the existing Tier-1 / Tier-2 gate**: if the cheaper model drops
   below the bar, the gate fails. The eval-driven rule ("only downgrade where the gate still
   passes") is enforced mechanically, not by hope; the `--baseline` A/B (ADR 0036) measures the
   quality/cost trade-off.

4. **Recommended tiers are documented, not auto-applied** (ADR consequences + `docs`): candidate
   downgrades (routing / grading / recall / simple synthesis → `simple`/`cheap`; implementation /
   design / security / adversarial review → `default`) are a starting point the user activates in
   settings and validates at that tier.

5. **Runtime Task delegation** (a skill body forking a role) can declare a model via the `model`
   frontmatter field (a documented Claude Code extension). This increment wires the deterministic,
   gate-validated **eval** path; auto-threading the resolved tier into live `Task` calls is left to
   the skill bodies / future work. **Update: closed by [ADR 0046](0046-runtime-model-routing.md)** —
   a committed `VALIDATED_TIERS` policy drives the agent `model:` frontmatter (Tier-0-enforced,
   sync-tool-regenerated), so the validated tier now reaches live delegation.

## Alternatives considered

- **Ship aggressive default downgrades (grader / router on sonnet by default):** rejected —
  Tier-1/Tier-2 are model-dependent and can't be pre-validated at the cheaper tier here; a default
  downgrade is an un-validated regression. Opt-in + gate-validated instead.
- **A model per skill in frontmatter only (no settings map):** rejected as the primary mechanism —
  frontmatter is static and not centrally tunable; a `settings.models` map is per-repo configurable
  and consumed by the gated runners. (Frontmatter `model` stays available for Task delegation.)
- **A global-default key inside `settings.models`:** rejected — the runner `--model` is the global
  default; per-component-only keys keep the map unambiguous.

## Consequences

- The plugin supports per-component model tiering (sonnet/haiku for simpler work), configured in
  `settings.models`, with opus the safe default; the eval gates validate any downgrade.
- No behaviour change by default; recorded Tier-2 numbers stand until a tier is configured (then
  re-record at that tier).
- Recommended tiers + the validate-before-flip rule are documented; runtime Task tiering via the
  `model` frontmatter is available — **auto-threading now closed by [ADR 0046](0046-runtime-model-routing.md)**
  (a committed, Tier-0-enforced policy drives the frontmatter).
