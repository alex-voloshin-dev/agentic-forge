---
name: deploy-watch
description: Read CI/CD pipeline state and monitoring alerts, assess rollout health (healthy / degraded / failing), triage the alerts, and recommend an action — recorded as a deploy-status handoff. Use to check deploy / rollout / pipeline health or status, watch a rollout, or assess CI/CD and alerts for an environment. Not for active incident handling (incident-response), cutting a release (release), or implementing a change (develop).
allowed-tools: Read, Grep, Glob, Bash, Write, Edit
---

# Deploy watch (phase workflow)

The rollout-observability phase: read an environment's CI/CD pipeline state and active alerts,
assess rollout health, and recommend an action — recorded as a `deploy-status` handoff. The
assessment lives in the installed `agentic_forge.ops` module; external state arrives through the
**adapter seam** (`PipelineSource` / `AlertSource`), so this skill is provider-agnostic. (Design:
[quality-ops.md](../../../docs/architecture/quality-ops.md).)

## When to use

When the task is to assess a deploy/rollout/pipeline's health or status for an environment. **Not**
for handling an active incident (`incident-response`), cutting a release (`release`), or building
(`develop`).

## Process

The ops helpers are an **installed module** — call them with Python; do not look for a file:

```
python -c "from agentic_forge import ops; help(ops.deploy_status)"
```

1. **Get the state through a source.** In a live repo, wire a real `PipelineSource` /
   `AlertSource` — the simplest is `connectors.pipeline_source(repo)` (auto-detects the `gh` CLI;
   see [references/connectors.md](references/connectors.md)), or an MCP connector / provider API —
   recent deploys + active alerts for the environment. When handed a recorded snapshot (JSON of
   `deploys` + `alerts`),
   load it into `ops.InMemoryPipeline` / `ops.InMemoryAlerts` (build `ops.Deploy` / `ops.Alert`
   from the records).
2. **Assess.** `ops.deploy_status(pipeline, alerts, environment)` returns the
   `deploy-status` mapping: `pipeline` health (`ops.rollout_health`: failing on a failed deploy or
   a `critical` alert; degraded on an in-flight deploy or a `warning`; else healthy), the deploy
   list, the `triage_alerts` counts, and a `recommended_action`.
3. **Record.** Write a `deploy-status` handoff artifact (`handoff` type `deploy-status`: `environment`, `pipeline`, `deploys`, `alerts`, `action`) and a
   short report; lead with the health and the recommended action.
4. **Recommend, don't act.** Never trigger a rollback or deploy — surface the action for a human.

## Output

A `deploy-status` handoff: environment, pipeline health, recent deploys, alert triage, and the
recommended action. No rollout action is executed.

## Definition of done

- Health is assessed via `ops.rollout_health` (failing > degraded > healthy) from the real state.
- Alerts are triaged; the recommended action matches the health (roll back on failing; continue on
  healthy).
- A valid `deploy-status` artifact is produced; no rollout action is executed.
