# 0038 — Token-overhead wiring via a `RunOutput` usage seam

Status: Accepted — **implemented** (see the [Unreleased] CHANGELOG entry).

## Context

[ADR 0036](0036-tier2-ab-overhead-wiring.md) wired the cheap Tier-2 signals — wall-clock time
overhead + the with/without A-B pass-rate lift — and **deferred token overhead** because the
`Runner` seam returns `str`: surfacing token usage looked like a cross-cutting signature change
touching every transport and every stub test. This ADR closes that deferral with a non-invasive
seam, so `max_overhead_tokens` becomes a live gate.

## Decision

1. **`RunOutput(str)` carries optional usage.** A transport may return
   `RunOutput(text, {"input_tokens", "output_tokens", "total_tokens"})`. Because `RunOutput` **is a
   `str`**, every existing consumer is unchanged — grading, JSON parsing, equality, and the
   `Runner = Callable[[str, str, Path], str]` type all still see a string; only the Tier-2 timing
   capture reads `.usage`. Stub runners and any text-only transport return a plain `str`, so
   token-overhead simply stays unmeasured for them — no caller or test breaks.

2. **The two production transports report usage.** `api_runner` reads the Anthropic Messages
   response `.usage`; `claude_cli_runner` switches from `--output-format text` to
   `--output-format json` and parses `{result, usage}`, **degrading to raw text with no usage** if
   the output is not the expected result-bearing JSON (so an odd/older CLI can't crash a sweep).
   `total_tokens = input_tokens + output_tokens`.

3. **`_run_passes` accumulates the component's tokens per run** into the timing entry
   (`total_tokens` alongside `duration_ms`). It sums only the component (`run_fn`) usage, **not the
   grader's** — the grader is eval machinery, and in the A-B delta a constant grader cancels, so the
   delta reflects the *skill's* marginal token cost. The rest of the chain was already built:
   `benchmark.summarize` emits `tokens` / `delta.tokens` only when a count is present, and
   `gate.tier2_quality` checks `max_overhead_tokens` against `delta.tokens`.

Token overhead is therefore live end-to-end under `--baseline`; with no usage (stubs / a text
transport) it stays silently absent, exactly as before.

## Alternatives considered

- **Change `Runner` to return `(str, usage)`:** rejected (as in ADR 0036) — it breaks every stub
  and caller for a second-order signal. `RunOutput` adds usage with zero signature churn.
- **A usage side-channel (a callback, or a mutable `.last_usage` on the callable):** rejected —
  stateful and ordering-fragile; a `str` subclass is the natural carrier (the reply value already
  *is* the string).
- **Keep `claude_cli_runner` on text and estimate tokens with a tokenizer:** rejected — an estimate
  is not the billed count; the CLI's JSON `usage` is authoritative and free.

## Consequences

- All Tier-2 overhead / A-B signals are now real: the pass-rate lower bound (always-on), and under
  `--baseline` the A-B lift + time overhead + **token overhead**. Version-over-version A/B was the
  last deferred signal — **now closed by [ADR 0047](0047-version-over-version-ab.md)** (a stored
  benchmark history + a `max_regression` gate).
- `claude_cli_runner` now emits JSON and extracts `result`; it degrades to raw text if the output
  is not parseable result JSON, so an unexpected CLI shape cannot crash a sweep.
- The grader's tokens are intentionally excluded from the overhead (component-cost semantics).
- CLAUDE.md §4, `overview.md`, `meta-core.md`, `eval-runbook.md`, and the `benchmark` docstring drop
  the "token-overhead deferred" caveat; the deferral note now names only version-over-version A/B.
