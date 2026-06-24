---
name: incident-response
description: Triage and drive an incident — classify severity (sev1-4), capture impact and timeline, coordinate mitigation, and draft a postmortem — recorded as an incident handoff. Use to start incident response, triage or classify an incident / outage / production issue, coordinate mitigation, or write a postmortem. Not for routine deploy / rollout monitoring (deploy-watch), cutting a release (release), or implementing a feature (develop).
allowed-tools: Read, Grep, Glob, Bash, Task, Write, Edit
---

# Incident response (phase workflow)

The incident phase: triage a production incident — classify severity, capture impact and timeline,
coordinate mitigation, and draft the postmortem — recorded as an `incident` handoff. The severity
classification is deterministic (`agentic_forge.ops.classify_incident`); the skill assembles the
record and drives mitigation before root cause. (Design:
[quality-ops.md](../../../docs/architecture/quality-ops.md).)

## When to use

When there is an active or recent incident to triage, coordinate, or write up — an outage, a
degradation, a sev-anything. **Not** for routine rollout monitoring (`deploy-watch`), cutting a
release (`release`), or implementing a fix from scratch (`develop`).

## Process

The ops helpers are an **installed module** — call them with Python; do not look for a file:

```
python -c "from agentic_forge import ops; print(ops.classify_incident(outage=True))"
```

1. **Assess the signal.** From the alerts/impact, determine the facts: is it a full **outage**?
   **data loss**? **degraded** (still working, slower/partial)? is there a **workaround**?
2. **Classify severity.** `ops.classify_incident(outage=…, data_loss=…, degraded=…, workaround=…)`
   → `sev1` (outage / data loss), `sev2` (degraded, no workaround), `sev3` (degraded, workaround),
   `sev4` (cosmetic / latent). Use the derived level — do not eyeball it.
3. **Assemble the record.** Write an `incident` handoff (`handoff` type `incident`: `severity`,
   `status`, `impact`, `timeline` — at least the detection event — `remediation`, `action_items`).
4. **Mitigate first, then root-cause.** Prioritize the fastest safe mitigation (a workaround or a
   rollback) over a root-cause fix. For an actual code fix or a security angle, fork the relevant
   role (`software-engineer` / `security-engineer`) via `Task`; keep the incident record updated.
5. **Postmortem.** Once resolved, complete the timeline, the root cause, and concrete action items
   (no blame).

## Output

An `incident` handoff: severity, impact, timeline, remediation, and action items — the live record
during the incident and the postmortem after.

## Definition of done

- Severity is classified via `ops.classify_incident` and matches the signal (outage → sev1, etc.).
- Impact, a timeline (≥ the detection event), and remediation are captured; mitigation is
  prioritized over root cause.
- A valid `incident` artifact is produced; the postmortem (when resolved) has action items, no blame.
