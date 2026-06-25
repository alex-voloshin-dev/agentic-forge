# Layer 4 — Guardrails (hooks)

Status: **Built** ([ADR 0019](decisions/0019-l4-guardrails.md)) — four deterministic guardrail
hooks on tool use, on top of L3's session-start hook. **Scheduling & observability shipped
separately** ([ADR 0024](decisions/0024-stage7-scheduling-observability.md),
[scheduling-observability.md](scheduling-observability.md)); this doc covers only the hooks.

The guardrails turn the project's discipline into **enforcement**: a hook deterministically
blocks (or warns) where a CLAUDE.md rule would only advise. They live under `plugin/hooks/`
(`hooks.json` + `scripts/`) as thin glue over `lib/agentic_forge/guardrails.py` (deterministic,
100% tested). Each hook **fails open** on its own error — a guardrail bug must never break a
session — except where blocking is the whole point (security, test-gate).

## The hooks

- **security** (`PreToolUse` / Bash, `security.py`) — blocks clearly-dangerous commands via a
  conservative deny-list: `rm -rf` of `/` or `~`, fork bombs, `curl|sh`, `mkfs`/`dd` to a device,
  `chmod 777 /`, raw-disk writes, force-push to a protected branch. Exit 2 blocks; everything else
  is allowed (false positives cause friction, so it blocks only unambiguous hazards).
- **test-gate** (`PreToolUse` / Bash, `commit_gate.py`) — on `git commit`/`git push`, runs the
  **fast** gate (`dev/validate.py` if present, else the detected stack's lint via `stacks.py`) and
  blocks on failure, so broken code isn't committed. Skippable via `AGENTIC_FORGE_SKIP_TEST_GATE`;
  fails open on an infrastructure error (missing tool, timeout).
- **budgets** (`PreToolUse` / Task, `budget.py`) — a per-session subagent counter; **warns** over
  the soft cap and **blocks** over the hard cap (`AGENTIC_FORGE_SUBAGENT_SOFT` / `_HARD`).
- **logging** (`PostToolUse`, `audit_log.py`) — appends a secret-redacted JSONL audit line to
  `<project>/.agentic-forge/audit.jsonl`. Pure observability; **never blocks**.

## Design notes

- **Deterministic, not LLM-judged** — blocking must be fast and predictable; the classifiers are
  tested deny-lists, conservative by design to avoid friction (the roadmap's stated risk).
- **Reuse** — the test-gate reuses by-stack (`stacks.py`); budgets use a session-scoped counter
  file; logging reuses the redaction in `guardrails.py`.
- **Exit-code contract** — `2` = block (reason on stderr, fed back to the model); `0` = allow (a
  non-blocking warning may still print to stderr).

## Eval model

- `guardrails.py` unit-tested on allow **and** block (100% line+branch); each hook script tested
  (block → exit 2, allow → exit 0, internal error → fail-open exit 0); `hooks.json` validated.
  mypy covers `plugin/hooks`.

## Beyond the hooks (shipped separately)

**Scheduling** (headless/CI cadence — knowledge-base re-scan, deploy-watch digests) and
**observability** (the audit-log digest) are not guardrails, so they live outside L4 — now
**built** in `schedule.py` / `observability.py` + the `run_scheduled` / `audit_digest` CLIs + a
cron workflow ([ADR 0024](decisions/0024-stage7-scheduling-observability.md)). A richer
observability dashboard remains an optional follow-on. L4 itself = the four hooks per CLAUDE.md.
