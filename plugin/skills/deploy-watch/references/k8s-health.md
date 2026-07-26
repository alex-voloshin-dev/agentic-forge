# Kubernetes cluster health check

How to run the deploy-watch assessment when the "environment" is a Kubernetes cluster/namespace
rather than a CI/CD pipeline. Field-derived: production audit logs showed a 2-hourly scheduled
cluster check (nodes → pods → events → deployments) as the single most common operation; this
reference makes that pass produce the same `deploy-status` handoff as the pipeline path.

## Read the state (read-only)

Scope to the target context/namespace explicitly; every command is a read:

```bash
kubectl --context <ctx> get nodes -o wide
kubectl --context <ctx> -n <ns> get deployments -o wide
kubectl --context <ctx> -n <ns> get pods -o wide          # restarts + phase live here
kubectl --context <ctx> get events -A --field-selector type!=Normal --sort-by=.lastTimestamp | tail -30
```

A recorded snapshot (JSON containing `nodes` / `deployments` / `pods` / `events_non_normal`,
possibly nested under a `cluster` key with an `as_of` capture time) is read the same way — assess
what is in the file, judge event recency against `as_of` (not today's clock), and never invent
state that is not there.

## Map observations → the health verdict

Same three-level verdict as `ops.rollout_health` (failing > degraded > healthy); pick the WORST
level any observation reaches:

| Observation | Level |
| --- | --- |
| Node `NotReady` / unreachable; a deployment at **0** available replicas; a namespace-wide crash pattern (many workloads restarting) | **failing** |
| A deployment below its desired available count (e.g. `2/3`); a pod in `CrashLoopBackOff` / `ImagePullBackOff` / repeated readiness failures; sustained non-Normal `Warning` events; node pressure conditions (`MemoryPressure`, `DiskPressure`) | **degraded** |
| All nodes `Ready`, all deployments at desired availability, no recent non-Normal events | **healthy** |

Triage the non-Normal events like alerts: `BackOff`/`Unhealthy`/`FailedScheduling` on one workload
= a `warning` count; anything implying data loss or total unavailability = `critical`. Restart
*counts* matter only with recency — 14 restarts with a fresh `BackOff` event is active; 14
restarts and silence for a week is history.

## Record it

The same `deploy-status` handoff as the pipeline path (`required`: `type`, `environment`,
`pipeline`):

- `environment` — the cluster/namespace checked (e.g. `production (aks/web)`).
- `pipeline` — the verdict, or a structured object (`{"health": "degraded", "cause": "report-service 2/3, CrashLoopBackOff"}`).
- `deploys` — the deployments list with ready/desired counts.
- `alerts` — the triaged non-Normal events (`{"critical": 0, "warning": 2}` or the raw list).
- `action` — targeted: name the workload and the next read (`kubectl logs`, `kubectl describe pod`);
  recommend a rollback only when the degradation maps to a specific recent rollout. Never execute
  a rollback/scale/delete — recommend only (the skill's standing rule).

## Scheduled / headless runs

For a recurring check, invoke the skill by name in a headless run so the session doesn't have to
rediscover the procedure:

```bash
claude -p "Use the deploy-watch skill: check the k8s cluster health for <ctx>/<ns> — nodes, pods,
deployments, non-Normal events — and record the deploy-status handoff." --allowedTools "Bash(kubectl:*),Read,Write"
```

Cadence guidance: match the check to how fast the state changes (the field precedent was every
2 h). Keep the run read-only (`kubectl` reads + the handoff write); pair it with the plugin's
scheduled-job registry (`docs/architecture/scheduling-observability.md`) if the repo already uses
`${CLAUDE_PLUGIN_ROOT}/bin/run_scheduled.py`.
