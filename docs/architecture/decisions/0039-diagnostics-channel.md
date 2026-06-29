# 0039 — Diagnostics channel: self-troubleshooting telemetry for the plugin

Status: Accepted — **implemented** (increment 1; see the [Unreleased] CHANGELOG entry).

## Context

The L4 audit log (`.agentic-forge/audit.jsonl`, written by the `audit_log` PostToolUse hook)
records tool **usage** — `{tool, input, session_id}` — and `observability.digest` rolls it into
per-tool counts. It is not an error channel. Today these signals **vanish**:

- **Guardrail denials / warnings** — `security` / `commit_gate` block (exit 2) and `budget` warns
  over a soft cap / blocks over a hard cap; none is recorded, so "what was blocked, how often" is
  unknowable after the fact.
- **Hook crashes** — `audit_log` and `security` fail-open (`except: pass`), so a guardrail bug is
  silent.
- **Pipeline anomalies** — a FAIL `GateResult`, an uncaught exception in a dev runner, an invalid
  handoff artifact — are not aggregated anywhere.

ADR 0024's observability doc already gestured at a digest over "blocks, budget warnings, errors",
but it was never wired: the audit records carry none of those fields and `observability.digest`
computes only tool counts (a doc-vs-code drift). This ADR adds the missing **diagnostics channel** —
errors and behaviour anomalies of *agentic-forge itself*, collected for later fix. Increment 1
covers the guardrail + pipeline emitters with a local sink + digest (the scoping chosen with the
user); workflow-flow capture and outward routing are deferred.

Scope is **plugin self-diagnostics** (the plugin's own machinery misbehaving, for the maintainers
to fix), distinct from target-repo incidents (which `incident-response` / `deploy-watch` own).

## Decision

1. **A dedicated diagnostics channel, separate from the usage audit.**
   `lib/agentic_forge/diagnostics.py` defines a redacted event —
   `{ts, kind ∈ block|warning|error|anomaly, severity (the handoff vocab), component, signature,
   message, context, session_id?}` — a thin `record_event` writer to `.agentic-forge/diagnostics.jsonl`
   (gitignored), and pure `digest` / `render` that group by **signature** (a stable fingerprint =
   component + kind + normalised message) into "top recurring problems". It mirrors
   `observability.py` (pure logic + a thin I/O seam). Separate from `audit.jsonl` because usage and
   problems differ in shape, volume, and audience; merging them would bloat the usage digest and
   couple the two.

2. **Capture at the deterministic boundaries only — hooks and CLIs — never in pure lib or the model
   flow.** Increment-1 emitters: the guardrail hooks (security / commit_gate denials, budget
   warn/block, hook crashes) and the dev runners (uncaught exceptions + gate/checkpoint FAILs). The
   pure lib (`gate`, `handoff`, `benchmark`) is untouched — it returns results; the impure boundary
   decides to emit. An invalid handoff artifact surfaces as an `anomaly` through the runner / e2e
   path that already validates artifacts.

3. **Never block, always redact, local-only.** Every emitter swallows its own errors (like
   `audit_log`) so diagnostics can never break a session or a run. All message/context strings pass
   through `guardrails.redact_secrets` (the channel captures inputs and exception text). It is **off
   by default**, gated by the `AGENTIC_FORGE_DIAGNOSTICS` env flag, and writes only to the local
   gitignored log — **no auto-exfiltration** (routing a digest to a GitHub issue / `incident-response`
   is a deferred, opt-in outward step).

4. **Rollup via the existing scheduler.** A `diagnostics-digest` `JOBS` entry + a
   `dev/diagnostics_digest.py` CLI produce a periodic "top problems" report through the existing
   cron CI — the same pattern as `audit-digest`.

5. **Timestamps passed in (pure core).** `make_event` takes `ts` from the caller (the impure
   emitter stamps it); the digest is deterministic and unit-tested, consistent with `schedule.py`.

6. **Fix the ADR-0024 drift.** The observability doc's promise of a digest over blocks/warnings/
   errors is realised by *this* channel (not by overloading the usage digest); the doc now points
   at it.

## Alternatives considered

- **Extend `audit.jsonl` with a `kind` field instead of a new file:** rejected — overloads the
  usage digest and couples problem-capture to the PostToolUse hook, but problems originate in many
  places (CLIs, denials) outside tool-use.
- **Emit from pure lib (`gate` / `handoff`):** rejected — couples deterministic, side-effect-free
  logic to I/O; capture belongs at the impure boundary.
- **On by default / auto-route to issues:** rejected for increment 1 — privacy + noise; the channel
  may capture inputs, so it is opt-in, local-first, with no outward action without explicit consent.

## Consequences

- Guardrail denials/warnings, hook crashes, and pipeline failures are collected (when enabled) into
  a redacted, gitignored `diagnostics.jsonl` and rolled up into a maintainer-facing "top problems"
  digest — closing the ADR-0024 gap.
- Default behaviour is unchanged (off unless the flag is set); never blocks; never leaks secrets;
  never sends anything outward.
- Deferred (increment 2+): workflow non-convergence (review-loop budget) capture, and opt-in
  outward routing of the digest.
