# 0042 — External reviewer (codex) as a subagent

Status: Accepted — **implemented** (planned-increment 2; see the [Unreleased] CHANGELOG entry).

## Context

Planned-increment 2: run an **external** reviewer CLI — `codex` only, for now — as a subagent, to
review code, a plan, or a product / technical document. A different model is a genuinely
**independent lens**: it catches what a same-family (`reviewer` role) pass misses, which is exactly
what `adversarial-review.md` wants from "fresh, independent" reviewers. It is gated by the settings
from increment 3 (`external_reviewer.{enabled,command}`, ADR 0041).

## Decision

1. **A `external_review.py` seam mirroring the connectors / `claude_cli_runner` pattern:** a pure
   parser + a thin subprocess seam.
   - `build_prompt(target, kind)` — `kind ∈ {code, plan, product, technical}` (extended with
     `research` and `ux` by [0061](0061-skeptic-loop-research-ux.md), `marketing` by
     [0062](0062-skeptic-loop-marketing.md)) selects the criteria
     and asks the CLI to return **only** the canonical review JSON (`verdict` +
     `findings[severity, location, issue, suggestion]`, the same vocab as the `review` handoff).
   - `is_available(command)` — `shutil.which`; absent → the reviewer degrades to "unavailable".
   - `run_external(command, prompt, workdir, *, runner)` — shells out via an **injected subprocess
     seam** (`runner`); the default real call is excluded from coverage (like `api_runner` /
     `claude_cli_runner`); **never raises** (returns `None` on absence / error / timeout).
   - `parse_review(output)` — **lenient**: reuses `agent_eval.parse_grading` to extract the JSON
     object from prose/fences, then normalises to `{verdict, findings[]}`; returns `None` if there
     is no well-formed review (the CLI may not follow the format).
   - `review(target, kind, *, command, workdir, runner)` — orchestrates the above; returns a
     review-shaped dict or `None`.

2. **A thin CLI `dev/external_review.py`** reads `settings` (`external_reviewer.command`, and refuses
   unless `enabled` or `--force`), runs the review on a target file, prints the verdict + findings,
   and can write a `review.md` handoff (`--out`) so a codex review feeds the existing review-loop /
   `review-scan` ecosystem.

3. **It is an optional, independent lens — not a gate.** Disabled by default; unavailable / disabled
   / unparseable all degrade gracefully (clear message, no crash). It does not replace the internal
   `reviewer`; `adversarial-review.md` documents it as an extra lens a review can add when enabled.

4. **Extensible to other CLIs later.** The command is configurable (`external_reviewer.command`),
   and the invocation lives in one place (`_argv`); only `codex` is wired/tested now.

5. **Safety — a reviewer must not mutate the repo (the security review's blocker).** `codex` is a
   coding *agent*; `codex exec` runs with write/shell tools by default. The seam therefore invokes
   it **read-only** — `exec --sandbox read-only` (mirroring the read-only grader's tool allowlist) —
   built in the pure `_argv` so the safeguard is a unit-tested invariant. The `command` is
   constrained by the schema to a **bare executable name** (`^[A-Za-z0-9][A-Za-z0-9_-]*$`), so a
   committed config can't point it at a path / shell line / arbitrary binary; the prompt is a single
   argv element (no shell). Findings are sanitised (single-line, severity clamped) before they reach
   `review.md`.

## Trust boundary (document, don't pretend away)

Running the external reviewer **sends the target's content (and, in-sandbox, repo context) to a
third-party agent**, and writes its output into `review.md`. So: it is **off by default**; do not run
it on secret-bearing targets; and the target is **attacker-controllable text fed to an agent**
(prompt-injection) — the read-only sandbox bounds that to *tainted findings* (an advisory verdict you
still review), not code execution. These limits are noted in `adversarial-review.md`.

## Alternatives considered

- **Model it as a generic `Runner` (system, prompt, workdir → str):** rejected — the use case is a
  *review* (structured findings), so a `review()`-returning-findings API is more useful than raw
  text the caller must re-parse.
- **Deep-integrate into the review-loop now (auto-add the codex lens in `develop`):** deferred — the
  loops run in the model's flow; wiring auto-invocation belongs with a later review-loop change. For
  now the CLI is the entry point and the pattern documents the lens.
- **Parse codex's free-form prose:** rejected — we instruct it to emit the canonical review JSON and
  parse that leniently; free-form prose is not reliably machine-readable.

## Consequences

- A codex review is available from the CLI (and can emit a `review.md`), gated by settings, for
  code / plan / product / technical targets — an independent lens for `deep-review` / the spine.
- Unit-tested with a stubbed subprocess (the real `codex` call is excluded from coverage, since it
  is not installed here); never raises, degrades gracefully when `codex` is absent.
- The exact `codex exec` invocation lives in one documented place; adjust there if a future codex
  CLI differs. Other external reviewers can be added behind the same `command` seam.
