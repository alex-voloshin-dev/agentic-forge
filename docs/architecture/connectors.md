# Real provider connectors

Implement the **existing** seams against real providers — no new seams. The `ops.py` Protocols
(`PipelineSource`, `AlertSource`) and the marketing → `research`/`Explore` path were built for
exactly this; "connectors" are their concrete implementations. Gated by `pytest` + Tier-0 (no new
model-invocable skills). Mechanism follow-on to ADR 0021 (ops seam) / ADR 0022 (marketing).

## Goal / non-goal

- **Goal:** concrete `PipelineSource` / `AlertSource` adapters + live market research, behind the
  current seams, so `deploy-watch` / `incident-response` / `marketing` work against real data.
- **Non-goal:** changing `ops.py`'s assessment logic, the skills, or the handoff schemas. A
  connector only produces `Deploy` / `Alert` objects (or feeds the research role).

## Where connectors live

`plugin/lib/agentic_forge/connectors.py` (promote to a `connectors/` package if it sprawls).
`ops.py` stays the Protocols + assessment; connectors implement the Protocols.

## Adapter shape: pure parser + thin fetch seam

Every connector splits the same way as `release.commits_since`:

- a **pure parser** `parse_*(payload) -> list[Deploy | Alert]` — fully unit-tested against fixture
  payloads (provider JSON / `gh` output), 100% covered;
- a **thin fetch seam** (`subprocess` / HTTP / MCP call) marked `# pragma: no cover` — the only
  un-tested line, never hit in CI.

So the logic that matters is deterministic and tested; nothing live runs in tests.

## Python adapter vs MCP (the key decision)

- **Structured CLI / simple REST** (GitHub Actions via `gh`, a plain status API) → a **Python
  adapter** (tested parser + thin call). Best for CI state — `gh` is ubiquitous and structured.
- **Providers that ship an MCP server** (Datadog, PagerDuty, Sentry, Grafana) → **MCP-first**: the
  skill discovers and uses the provider's MCP tool (via `ToolSearch`); auth and pagination are the
  MCP server's job. A Python REST adapter is only the fallback. Rationale: avoid bespoke HTTP +
  credential code where Claude Code's native MCP already integrates the provider.
- **Market research** → native **`WebSearch` / `WebFetch`** through the existing `research` /
  `Explore` fork — no connector code, just wiring + the evidence/citation discipline already gated
  in marketing's Tier-2.

## Selection & configuration

A connector is chosen by a small config plus auto-detect:

- `.agentic-forge/connectors.toml` (or env) names the provider + settings per concern
  (`pipeline`, `alerts`); unset → **auto-detect** (e.g. use `gh` if it's on `PATH`).
- Credentials come from the environment / the MCP server config — **never** committed. Any logging
  goes through `guardrails.redact_secrets`.

## How connectors plug in (no skill/core change)

- `deploy-watch` / `incident-response`: their SKILL.md already say "wire a real `PipelineSource` /
  `AlertSource`." Add `references/connectors.md`: select connector → call `ops.deploy_status` /
  `ops.classify_incident` exactly as today.
- `run_scheduled.py`'s `deploy-digest` action: use the configured pipeline + alert connectors;
  fall back to today's "no provider source configured" message when none is set.

## Phased rollout

1. **`GhPipelineSource`** (Python adapter, tested) — **✅ shipped** (`connectors.py`): GitHub
   Actions `gh run list --json` → `Deploy` (`success→passing`, `failure→failing`,
   `in_progress→running`, `queued→queued`); `pipeline_source(repo)` auto-detects `gh`. Wired into
   `deploy-watch` (references/connectors.md) + the scheduled `deploy-digest`.
2. **`AlertSource`** — **✅ Grafana shipped** (`GrafanaAlertSource`): `parse_grafana_alerts` (pure,
   tested) maps Grafana Alertmanager alerts → `Alert`; `alert_source()` reads `GRAFANA_URL` /
   `GRAFANA_TOKEN`. MCP-first per policy (prefer the Grafana MCP tool; REST is the fallback). Wired
   into deploy-watch + incident-response references and the scheduled `deploy-digest`.
   Datadog / PagerDuty are siblings behind the same Protocol.
3. **marketing → `WebSearch`** — **✅ shipped**: `marketing` gains `WebSearch` / `WebFetch` tools;
   its market-research procedure gathers live market/competitor data and records every source URL,
   under the evidence-discipline already gated in Tier-2. No connector code (native tools).

## Alternatives considered

- **Bespoke HTTP client per provider** — rejected where an MCP server exists (auth + maintenance
  burden); MCP-first there, Python only for structured CLIs/REST.
- **New abstractions/seams** — rejected; the `ops.py` Protocols already fit.
- **A connector "skill"** — rejected; connectors are infra behind the Protocols, not a workflow
  (router discipline).

## Exit criteria (per phase)

- Parser 100% unit-tested on fixture payloads; fetch seam `# pragma: no cover`; selection logic
  tested.
- Wired into the skill reference + `run_scheduled`; no live provider in tests/CI.
- Tier-0 + full suite green; docs + CHANGELOG per phase.
