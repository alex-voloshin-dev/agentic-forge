# 0052 — Analyzable production diagnostics: valid-JSON audit records + a one-command bundle

Status: Accepted — implemented (see the [Unreleased] CHANGELOG entry).

## Context

To fix the plugin from real usage, a maintainer needs the plugin's own logs from a production
session. Today that is assembled by hand, and the raw material is partly unreadable:

- **The audit log corrupts long records.** `guardrails.audit_record` serialises the whole
  `tool_input` to a JSON string, then truncates *that string* at 300 chars and appends `…`. The
  result is **invalid JSON inside the `input` field**. In a real bundle, **441 of 740 (60%) Bash
  records were unparseable** — exactly the long commands (multi-line kubectl/curl pipelines) that
  matter most for debugging. The very feedback loop the audit log exists for is degraded.
- **No packager exists.** There is a diagnostics *channel* (`diagnostics.py`, ADR 0039) and digest
  CLIs, but nothing collects the audit log, the diagnostics log, environment, and the plugin/config
  metadata into one consistent, redacted, shareable artifact. Bundles were being assembled ad hoc,
  so their structure (and their redaction guarantees) varied session to session.

## Decision

Two changes, both serving "consistent, structured, analyzable diagnostics from production":

**1. Audit records stay valid JSON.** `audit_record` now redacts and truncates **each field value**
of `tool_input` (recursively) and *then* `json.dumps` the result. The `input` field remains a JSON
string (no schema change for existing consumers), but it is **always valid JSON** — a downstream
tool can `json.loads(rec["input"])["command"]` and recover the (per-field-capped) command.
Truncation is per-value, so no field can be cut mid-encoding.

**2. A deterministic bundle packager** — `lib/agentic_forge/diag_bundle.py` (pure `plan_bundle`
building the file manifest + redacting the config/settings slices) and a thin `dev/
diagnostics_bundle.py` CLI (`build_bundle` writes the zip). One command produces the same structure
every time:

    agentic-forge-diagnostics-<ts>/
      README.md                              generated: what this is + the signal
      log-summary.txt                        observability.digest + diagnostics.digest
      environment.txt                        OS / node / python / claude-code / plugin versions
      repo-logs/audit.jsonl                  copied (already hook-redacted)
      repo-logs/diagnostics.jsonl            copied (already hook-redacted)
      user-config/config.json                ~/.agentic-forge/config.json (redacted)
      plugin-meta/{plugin.json, installed_plugins.json, settings-agentic-forge.json}

Redaction is defence-in-depth: the logs are already redacted at write time (ADR 0019/0039), and the
config/settings slices pass through `guardrails.redact_secrets` again; the settings slice keeps only
enablement + hooks (never tokens). The pure manifest builder is unit-tested; the zip write is a thin
seam.

## Alternatives considered

- **Make `input` a structured object** (dict instead of a JSON string): rejected as the fix for (1)
  — it changes the audit schema for every consumer and every existing on-disk log; keeping `input`
  a *valid* JSON string is backward-compatible and enough.
- **Just raise the 300-char cap:** rejected — a bigger cap still corrupts JSON at *its* boundary;
  the defect is truncating an already-encoded string, not the length.
- **Ship the bundler as a skill/hook that auto-fires:** deferred — start with an explicit,
  deterministic CLI (importable core, so a session can call it via `${CLAUDE_PLUGIN_ROOT}/lib`); a
  skill/command surface can wrap it later without changing the core.

## Consequences

- Audit records are fully machine-readable again; `tests/test_guardrails.py` asserts
  `json.loads(rec["input"])` round-trips and stays capped, replacing the old "ends with …" string
  assertion.
- A maintainer (or an in-session agent) runs one command to produce a consistent, redacted bundle;
  `tests/test_diag_bundle.py` covers the manifest, redaction, and secret-free guarantees.
- Documented in `docs/architecture/scheduling-observability.md`; `diag_bundle.py` is added to the
  meta-core library table (Tier-0 doc-sync).
