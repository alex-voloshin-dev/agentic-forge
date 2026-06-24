# 0025 — Real provider connectors: implement the existing seams (Python for CLI/REST, MCP-first for monitoring)

Status: Accepted

## Context

`deploy-watch` / `incident-response` run their assessment through the `ops.py` Protocols
(`PipelineSource`, `AlertSource`), backed today by in-memory fakes; `marketing` gathers evidence
through the `research` / `Explore` fork. Those seams were built (ADR 0021, ADR 0022) precisely so
real providers could be wired later without touching the skills or the assessment logic. This ADR
decides **how**. Full design in [connectors.md](../connectors.md). No new model-invocable skills →
gated by `pytest` + Tier-0.

## Decision

- **Implement the existing seams; add no new ones.** A connector only produces `Deploy` / `Alert`
  objects (or feeds the research role). `ops.py`'s logic, the skills, and the handoff schemas are
  untouched. Connectors live in `lib/agentic_forge/connectors.py`.
- **Every connector = a pure parser + a thin fetch seam.** `parse_*(payload) -> [...]` is unit-
  tested against fixture payloads (100% covered); the `subprocess`/HTTP/MCP call is `# pragma: no
  cover`. Same split as `release.commits_since` — deterministic logic tested, nothing live in CI.
- **Python adapter vs MCP, by provider shape:**
  - structured CLI / simple REST (GitHub Actions via `gh`) → a **Python adapter**;
  - providers that ship an **MCP server** (Datadog, PagerDuty, …) → **MCP-first** (the skill uses
    the provider's MCP tool via `ToolSearch`; auth is the MCP server's job), with a Python REST
    parser only as fallback;
  - market research → native **`WebSearch` / `WebFetch`** through the existing research fork (no
    connector code).
- **Selection by config + auto-detect.** `.agentic-forge/connectors.toml` (or env) names the
  provider per concern; unset → auto-detect (e.g. `gh` on `PATH`). Credentials from env / MCP
  config, never committed; logging via `guardrails.redact_secrets`.
- **Phased:** (1) `GhPipelineSource` (Python, tested) for CI state; (2) `AlertSource` MCP-first +
  REST fallback; (3) marketing → `WebSearch` wiring. Ship phase 1 first (provider-neutral, useful
  now, feeds `deploy-watch` + scheduled `deploy-digest`).

## Alternatives considered

- **A bespoke HTTP client for every provider** — rejected where an MCP server exists (auth +
  maintenance burden); MCP-first there, Python only for structured CLIs/REST.
- **New abstractions / seams** — rejected; the `ops.py` Protocols already fit.
- **A connector "skill"** — rejected; connectors are infrastructure behind the Protocols, not a
  conversational workflow (router discipline).
- **Live providers in tests** — rejected; parsers test on fixtures, fetch is a no-cover seam.

## Consequences

- A `connectors.py` of provider adapters, each a tested parser + thin seam; `deploy-watch` /
  `incident-response` gain real data via their existing references; `run_scheduled`'s
  `deploy-digest` uses the configured connector (graceful fallback when unset).
- MCP-first keeps the codebase small and defers auth to Claude Code's MCP layer.
- Each provider is its own additive phase; the stack-specific choice (which CI, which alerting) is
  the adopting repo's, driven by config.

## Exit criteria (per phase)

- Parser 100% unit-tested on fixture payloads; fetch seam `# pragma: no cover`; selection tested.
- Wired into the skill reference + `run_scheduled`; no live provider in tests/CI.
- Tier-0 + full suite green; docs + CHANGELOG per phase.
