# 0053 — A `diagnostics-bundle` skill: windowed, ~/Downloads, consistent naming

Status: Accepted — implemented (see the [Unreleased] CHANGELOG entry).

## Context

ADR 0052 added the bundle *core* (`diag_bundle.build_bundle`) and a maintainer `dev/` CLI. But
`dev/` is not shipped with the installed plugin, so a user in a production session had no first-class
way to produce a bundle, and the ad-hoc invocations varied in window, destination, and filename. To
get *consistent* diagnostics from real usage, the packaging needs to be a shipped, one-command skill
with a fixed contract: a bounded time window, a strict destination, and a stable name.

A second gap surfaced: the audit log records had **no per-record timestamp** (`{tool, input,
session_id}`), so "the last 7 days" could not be honoured for the audit trail — only the diagnostics
log (which carries `ts`) was time-filterable. (The same missing timestamp also hampered the offline
analysis that motivated ADR 0051/0052.)

## Decision

**1. Timestamp the audit trail.** `guardrails.audit_record` gains an optional `ts` (the hook stamps
`datetime.now(timezone.utc)`; the function stays pure — the caller supplies the clock). Records are
now time-windowable; the change is backward-compatible (a new optional field; legacy records simply
lack it).

**2. Window + destination in the core.** `diag_bundle` gains pure helpers — `filter_by_window`
(keep records within the last N days; **retain** blank/malformed/undated records so a window never
silently drops what it cannot date), `window_text` (the human-readable range), and
`default_output_path` (`<home>/Downloads/<prefix>-<ts>.zip`). `build_bundle` defaults to a **7-day**
window and, when no `out_path` is given, to that strict `~/Downloads` destination; the covered
window is written into the README and `log-summary.txt`.

**3. A shipped skill.** `plugin/skills/diagnostics-bundle/` — `SKILL.md` (a short manual workflow),
a shipped `scripts/build_bundle.py` (a thin wrapper importing the lib from `${CLAUDE_PLUGIN_ROOT}/
lib`), and `evals/evals.json`. It is **off-listing** (`disable-model-invocation: true`): a rare
maintainer utility should not spend the always-on router budget (CLAUDE.md principle 2), so it is a
manual `/`-command whose description never enters the listing. Being self-contained (it does the
work directly, not via a delegated role), it declares a Tier-2 quality contract per ADR 0017.

## Alternatives considered

- **Auto-triggering (on-listing) skill:** rejected — the on-listing set is already at the ~1% budget
  ceiling; a rarely-used export utility does not earn a slot. Manual `/`-invocation fits its use.
- **Filter the audit log by file mtime instead of adding `ts`:** rejected — mtime is the *whole
  file*, not per record; it cannot window a single appended log. Per-record `ts` is the honest fix
  and is broadly useful (usage-over-time analysis).
- **Drop undated records outside the window:** rejected — legacy audit lines predate `ts`; dropping
  them would silently hide history. Retain-and-note is safer for a diagnostics artifact.
- **Only expose the `dev/` CLI:** rejected — not shipped to user repos; the whole point is a
  production-session-reachable, consistent packager.

## Consequences

- One manual command (`/agentic-forge:diagnostics-bundle`, or the script directly) produces a
  redacted, consistently-named `~/Downloads/agentic-forge-diagnostics-<ts>.zip` for the last 7 days
  (or a user-given window; `0` = full history), with the window stated in the report.
- The audit trail is time-aware going forward; `filter_by_window`, `window_text`,
  `default_output_path`, the `ts` stamp, the dev CLI `--days`, and the shipped skill script are all
  covered by `tests/test_diag_bundle.py` / `test_guardrails.py` / `test_dev_cli.py`.
- The skill is off-listing, so the router budget and the Tier-1 on-listing set are unchanged; it is
  added to the Tier-2 registry (`test_skill_eval.py`).
