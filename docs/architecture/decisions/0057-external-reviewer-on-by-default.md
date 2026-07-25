# 0057 — External reviewer on by default, wired into develop + product

Status: Accepted — **implemented**. Updates [0042](0042-external-reviewer.md) (external reviewer
seam) and its trust-boundary posture; builds on [0041](0041-plugin-settings.md) / [0049](0049-user-level-config.md)
(settings) and the [multi-aspect-review](../../../plugin/patterns/multi-aspect-review.md) /
[adversarial-review](../../../plugin/patterns/adversarial-review.md) patterns.

## Context

ADR 0042 shipped the external reviewer (`codex`) as a pure seam plus a CLI, deliberately **off by
default** and **not wired into any workflow** — it existed only as a manual `dev/external_review.py`
entry point and as an optional lens documented in `adversarial-review.md`. In practice that meant the
independent-model lens was never exercised by the SDLC spine: `develop` reviewed with the internal
same-family roster (`reviewer` + `security-engineer` + lint), and `product` with an internal skeptic
pass. The maintainer wants the external, *different-model* lens to be a first-class part of the
review cycle so it catches what a same-family pass structurally misses.

## Decision

1. **On by default.** `external_reviewer.enabled` defaults to **`true`** (`settings.DEFAULTS`,
   `config.example.json`, `configuration.md`). The per-repo / user / env precedence (ADR 0041/0049)
   is unchanged — set `false` to opt out.

2. **Auto-invoked as an extra lens in two workflows:**
   - **`develop`** — inside the multi-aspect review gate (step 4), the external reviewer runs over
     the *same integrated diff* with `--kind code`. Its findings fold into the aggregated
     approve/changes verdict at their own severity, so they participate in the **bounded N = 3
     review loop** (step 4 → step 5): a blocker/major from codex drives a `changes` verdict →
     loop back to implementation; clean → proceed. This is the implementation → review →
     (loop-on-signals | advance) cycle, now with the external lens inside it.
   - **`product`** — inside the skeptic pass (step 6), the external reviewer critiques `prd.md`
     with `--kind product`; its findings feed the same worst-first, bounded revision loop.

3. **The prompt contract is unchanged (the "review skill" is ours).** codex is still driven by
   `external_review.build_prompt(target, kind)` — our per-kind criteria + the strict
   `{verdict, findings[]}` JSON contract — invoked `codex exec --sandbox read-only`. We deliberately
   do **not** hand codex a bare "review this" and rely on its own built-in review behaviour: the
   strict contract keeps the output machine-parseable and severity-comparable with the internal
   aspects (so one verdict can aggregate both). "Runs with its review skill" means *our* review
   prompt, not codex's free-form judgement.

4. **Graceful degradation is the safety valve for on-by-default.** `is_available()` gates every
   call: on a machine without `codex` on PATH (the common case), the lens is **skipped, not a
   failure** — the workflow proceeds on the internal roster exactly as before. `run_external` never
   raises. So "on by default" means "used wherever codex is installed", not "every user now ships
   code to a third party regardless".

## Trust boundary (the cost of the default flip)

On-by-default means: **wherever `codex` is installed and `enabled` is left true, the target's
content is sent to a third-party agent (OpenAI) on every review iteration.** The mitigations from
ADR 0042 still bound this and are why the flip is acceptable:

- **Read-only sandbox** (`exec --sandbox read-only`, a unit-tested invariant in `_argv`) — the
  reviewer cannot mutate the repo or run shell, so a prompt-injected target yields *tainted advisory
  findings*, not code execution.
- **`command` is a bare executable name** (schema-constrained) and the prompt is a single argv
  element — no shell injection.
- **Findings are sanitised** (single-line, severity clamped) before they reach `review.md`.
- **Advisory, verified.** Every external finding is verified against the source before it drives the
  verdict, like any finding in the multi-aspect / adversarial patterns.

**Opt-out guidance is explicit:** set `external_reviewer.enabled: false` on secret-bearing repos.
This is documented in `configuration.md`, both review patterns, and `extensions.md`.

## Alternatives considered

- **Keep it off by default (0042 status quo):** rejected per the maintainer's explicit ask — the
  independent lens should be exercised by the spine, not left as a manual CLI.
- **Hand codex its own built-in review skill (bare prompt, parse free-form prose):** rejected — free
  prose is not reliably machine-readable and its severities can't be aggregated with the internal
  aspects into one verdict. We keep the strict JSON contract (0042) and treat *our* prompt as the
  review skill.
- **Wire it into every review surface (code-review, deep-review, security-review too):** deferred —
  `develop` and `product` are the two the maintainer named; `deep-review` already documents the lens
  via `adversarial-review.md`. Others can adopt the same one-line call later.

## Consequences

- The external, different-model lens now runs by default inside `develop`'s code-review gate and
  `product`'s skeptic pass, folding into their existing bounded loops — no new loop machinery.
- On machines without `codex`, behaviour is unchanged (graceful skip); on machines with it, code /
  PRDs are sent to a third party each review iteration unless the repo opts out.
- ADR 0042's seam, prompt contract, and read-only invariant are unchanged; only the default and the
  two wiring points are new.
