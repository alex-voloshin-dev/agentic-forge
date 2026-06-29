# Plugin extensions (post-Stage-7)

After the five layers (L0–L4) and the SDLC domains were built, a set of **cross-cutting plugin
extensions** were added — configuration, model routing, and two outward-facing review/automation
seams. They are not a new layer: each plugs into the existing engine, guardrails, or eval gates.
This document is their narrative home; the per-decision detail lives in the linked ADRs.

All of these follow the same house style as the connectors: a **pure, fully-tested core plus a thin
injected seam** for the live call, the seam excluded from coverage. None of them changes default
behaviour — every one is opt-in.

## Configuration (`settings.py`, ADR 0041 / 0049)

One resolver for the plugin's knobs, over a layered precedence:

```
built-in DEFAULTS  <  user-level ~/.agentic-forge/config.json  <  per-repo .agentic-forge/config.json  <  env vars
```

So a user sets defaults once in their home, a repo overrides them per-project, and CI / one-off env
vars still win. Both files are validated against [`config.schema.json`](../../plugin/schemas/config.schema.json).
`resolve()` **never raises**: a missing file is defaults; a malformed file is defaults + a one-line
stderr warning. `jsonschema` is imported lazily and is optional, so a guardrail hook can resolve
settings under a bare `python3` without the plugin's third-party deps (ADR 0050). Every other
extension here reads its on/off switch and parameters from this resolver. Full key reference:
[configuration.md](../configuration.md).

## Model tiering & runtime routing (`models.py`, ADR 0043 / 0046)

Cheaper models (sonnet / haiku) for simpler work, the strongest (opus) for hard work. Tiering is
**opt-in** via `settings.models` and **validated by the eval gates** — Tier-1 / Tier-2 are
model-dependent, so a downgrade only ships where the component still passes its gate at the cheaper
tier. With an empty `settings.models` every component resolves to the global `default` (no behaviour
change). Runtime routing (ADR 0046) closes the loop: `models.frontmatter_model(name)` maps the
validated tier onto each agent's `model:` frontmatter, and Tier-0 (`validate_agent`) **fails** if an
agent's committed `model:` drifts from the validated policy — so live `Task` delegation can never run
on an unvalidated tier. `dev/sync_models.py` regenerates the frontmatter from the policy.

## External reviewer seam (`external_review.py`, ADR 0042)

A different model is an independent review lens — it catches what a same-family `reviewer` pass
misses (see [adversarial-review.md](../../plugin/patterns/adversarial-review.md)). This seam runs a
third-party reviewer CLI (e.g. `codex`) as that extra lens: a pure `build_prompt` / `parse_review`
core plus a thin subprocess seam that **never raises** and degrades gracefully when the CLI is
absent. Gated by the `external_reviewer.{enabled,command}` settings; off unless configured.
Driver: `dev/external_review.py`.

## PR watcher (`pr_watch.py`, ADR 0044 / 0045)

Parse a GitHub PR's review state from the `gh` GraphQL JSON and drive a **bounded** fix loop:
plan a response to each review thread, build the `gh` / `git` commands, optionally run an injected
`fixer`. Pure parsing / planning over the JSON; the live `gh` / `git` writes and the model fix are
thin injected seams (excluded from coverage, like the connectors). It is off by default and
dry-run unless the caller passes a live `fixer` / `gh_exec` / `push`, and it **never merges** and
**never force-pushes** — there is deliberately no merge/force command builder. Driver:
`dev/pr_watch.py`.

## Related, documented elsewhere

- **Ralph loop** (`ralph.py`, ADR 0048) — bounded autonomous iteration; see
  [the engine overview](overview.md) and [`patterns/ralph.md`](../../plugin/patterns/ralph.md). It
  is CLI-driven (`dev/ralph.py`), not composed into a skill.
- **Self-diagnostics** (`diagnostics.py`, ADR 0039) — the plugin's own error/anomaly channel; see
  [scheduling & observability](scheduling-observability.md).
- **Review-loop non-convergence scan** (ADR 0040) and **hook import safety** (ADR 0050) — guardrail
  hardening; see [guardrails](guardrails.md).
</content>
</invoke>
