# 0078 — The audit trail gets an off switch (`logs.enabled`), default on

**Status:** Accepted (implemented)
**Date:** 2026-07-26
**Evidence:** a production repo running 2026.7.9, reported the same day.

## Context

ADR 0072 moved every generated file out of the user's repository. It is on `master` and **not yet
released**, so an installed 2026.7.9 still writes `<repo>/.agentic-forge/`. A production user hit
the practical consequence: they moved 8.1 MB of audit log and the directory **reappeared within 16
seconds** — recreated by the `PostToolUse` hook recording the very `mv` that emptied it.

Their diagnosis was right, and it exposed something ADR 0072 did not address. Of the four state
writers, three can be stopped:

| Writer | Off switch in 2026.7.9 |
| --- | --- |
| diagnostics | `diagnostics.enabled` (and off by default) |
| schedule state | only written when the runner is invoked |
| pr-watch queue | `pr_watcher.enabled` + `auto_watch` |
| **audit log** | **none — writes on every tool call, unconditionally** |

So a user who wants the plugin's guardrails but not its audit trail has no supported answer. The
only remedies were editing `hooks.json` inside the installed plugin, or uninstalling.

## Decision

Add `logs.enabled` (ADR 0041's config layering, same shape as `diagnostics.enabled`), honoured by
`hooks/scripts/audit_log.py`, overridable with `AGENTIC_FORGE_LOGS`.

**Default: on.** The audit trail is the only record of what the agent actually did, and it is the
substrate the field reports this project runs on are built from — including the bundle that
produced ADRs 0072–0075. Shipping it off by default would quietly remove the evidence channel to
save a file. The defect was never that it records; it was that it recorded with **no way to say
no**.

`write_audit` now returns `Path | None` — `None` meaning "gate off", distinct from an exception,
so a caller can tell "deliberately not written" from "failed to write".

## Consequences

- **A user can decline the audit trail** without editing the installed plugin.
- **Nothing changes by default**, so no existing installation loses its trail on upgrade.
- **This is not a fix for the in-repo path** — that is ADR 0072, and it needs the release. Turning
  the gate off stops the *writing*; it does not move the file. A 2026.7.9 user who wants the
  directory gone today must both disable the gate and upgrade.
- **Turning it off blinds the diagnostics bundle**, which is what a maintainer asks for when
  something goes wrong. Worth stating to anyone who disables it.
- **Volume is still unaddressed.** 8.1 MB in ten days on one active repo extrapolates to ~300 MB a
  year. Rotation exists (`observability.rotate_audit`, once per session, keep-the-tail) and
  evidently did not keep up. Not changed here — a gate is not a retention policy, and the right
  bound needs its own measurement.
