# 0058 — Field-driven diagnostics fidelity (from a production bundle analysis)

Status: Accepted — **implemented**. Extends [0039](0039-diagnostics-channel.md) (diagnostics
channel), [0019](0019-l4-guardrails.md) (guardrail hooks), [0052](0052-diagnostics-bundle-and-audit-fidelity.md)
/ [0053](0053-diagnostics-bundle-skill.md) (bundle + audit fidelity).

## Context

A real 14-day diagnostics bundle from a production repo (459 raw sessions / 108,910 events
vs 12,777 audit records vs 10 diagnostics events) was compared against the raw Claude Code
transcripts as ground truth. Four gaps surfaced:

1. **`commit-gate` false-positive blocks.** All 10 diagnostics events were commit-gate blocks, and
   **none was a real code-quality failure** — they were `npm run lint` failing with `Missing script:
   "lint"` or `eslint: command not found`. The gate treats a *non-zero exit it cannot attribute to
   the linter itself* (a missing script / missing tool / missing file) as a genuine failure and
   blocks the commit. That is environment breakage, not a quality signal — it should fail **open**,
   like the existing `except` path does for a subprocess that never starts.
2. **A silent audit-coverage hole.** 84 main (non-sidechain) sessions with 3,839 tool calls
   (2026-07-04 .. 07-15) had **zero** audit records; coverage jumps to 100% from 07-16, exactly when
   the repo updated to 2026.7.2 (the `f1e23ac` "observability hygiene" fix that moved the audit log
   to `main_repo_root`). The hole was **invisible from inside the diagnostics** — only the raw-vs-
   audit comparison revealed it. A bundle should be able to *disclose its own coverage* the way it
   already discloses legacy-record share (ADR 0052 `audit_quality`).
3. **The audit trail records no outcome.** A record is `{tool, input, ts, session_id}` — no
   success/error. 441 failed tool calls (`is_error:true`) in the raw sessions are invisible in both
   audit and diagnostics, so "what actually breaks in the field" can't be read from the trail.
4. **The digest can't surface failing tools.** With no outcome recorded, `log-summary.txt` can only
   rank tools by usage, not by failure — the single most useful triage view.

## Decision

1. **`commit-gate` fails open when the gate can't run (gap 1).** A pure
   `guardrails.gate_unrunnable(output)` recognises the "not a quality failure" signatures in the
   gate's combined output — `missing script`, `command not found`, `no such file`, `not found`,
   `can't open file`, `ModuleNotFoundError`, `executable ... not found`. On a non-zero exit whose
   output matches, `commit_gate` does **not** block: it emits an `anomaly` diagnostics event
   (component `commit-gate`, "gate unrunnable") and allows the commit. A non-zero exit that does
   **not** match still blocks (real lint/test failures). This is the same fail-open philosophy the
   `except` path already uses for a subprocess that fails to start.

2. **The bundle discloses its audit coverage (gap 2).** A pure
   `diag_bundle.session_coverage(audit_sessions, transcript_sessions)` compares the session ids in
   the audit trail against the Claude Code transcripts for the repo (a thin, best-effort I/O seam
   reads only each transcript's `sessionId` / `isSidechain` / whether it has a `tool_use`, never the
   content). It reports `main sessions with tool activity`, `represented in audit`, and `missed`, and
   the README / `log-summary.txt` show a one-line **Coverage** disclosure. Best-effort: if the
   transcripts aren't readable, the line is omitted (never fatal, never a leak — transcript content
   is never shipped).

3. **The audit record carries an error flag (gap 3).** `guardrails.audit_record` adds `"error":
   true` when a pure `guardrails.tool_errored(payload)` finds a reliable failure signal in the
   PostToolUse payload (`tool_response.is_error` true, an `is_error` top-level flag, or a
   `tool_response` string beginning `Error:`). It is **conservative** — only a clear signal sets the
   flag, so a healthy call is never mislabelled — and additive (absent on success), so old readers
   and the JSON-validity guarantee (ADR 0052) are unaffected.

4. **The digest ranks failing tools (gap 4).** `observability.Digest` gains `errors` (count of
   records with `error: true`) and `by_error_tool` (per-tool failure counts, descending); `render`
   adds a "Failures" section when any errors are recorded. So `log-summary.txt` shows *which* tools
   fail most, not just which run most.

5. **Hook self-diagnostics: confirmed already present, one limit documented.** Every hook
   (`security`, `commit_gate`, `budget`, `audit_log`, `session_start`) already emits a diagnostics
   `error` event when its body raises (ADR 0039), so a hook *crash* is not silent. The one residual
   blind spot is a hook **killed by the harness on timeout** (SIGKILL/SIGTERM is not catchable in
   `except`): that path stays silent, and gap-2's coverage disclosure — not hook self-diagnostics —
   is the safety net for the resulting data loss. Documented, not code-changed.

## Alternatives considered

- **commit-gate: parse the linter's own exit taxonomy per stack:** rejected — brittle across
  npm/eslint/ruff/etc.; the output-signature denylist is simple, testable, and matches the field
  failure modes directly. A false "unrunnable" match at worst downgrades a block to an anomaly (fail
  open), which is the safe direction for a guardrail.
- **coverage: ship transcript excerpts as proof:** rejected — the transcripts are unredacted (the
  `with-sessions` comparison bundle exists precisely because they must not ship). Coverage reads only
  session metadata and ships only the counts.
- **audit: record stdout/stderr tails per call:** rejected — size + redaction risk; a boolean
  `error` flag is enough to rank failures, and details already live in the transcripts.

## Consequences

- A missing lint script / uninstalled linter no longer blocks commits (the field's actual friction);
  real failures still block. Fail-open is recorded as an `anomaly`, so the downgrade is auditable.
- Bundles now disclose coverage, so a future audit-hole like gap 2 is visible from the bundle alone.
- The audit trail marks failed calls, and the summary ranks failing tools — field triage no longer
  needs the 353 MB raw firehose for "what breaks".
- All additive: existing records/readers, the JSON-validity guarantee, and the redaction posture are
  unchanged.
