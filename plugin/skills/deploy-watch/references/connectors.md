# Wiring a real pipeline source (connectors)

`deploy-watch` assesses rollout health through the `ops.PipelineSource` / `ops.AlertSource`
seams. In a live repo, use a real connector instead of a recorded snapshot (ADR 0025):

```
python -c "
from agentic_forge import connectors, ops
pipeline = connectors.pipeline_source('.')            # a checkout path or 'OWNER/REPO'; gh on PATH -> GhPipelineSource
alerts   = connectors.alert_source()                  # GrafanaAlertSource if GRAFANA_URL set, else empty
print(ops.deploy_status(pipeline, alerts, 'production'))
"
```

- **`connectors.pipeline_source(repo)`** takes a checkout **path** or an `owner/name` slug (a path
  is resolved through its `origin` remote) and auto-detects the **`gh` CLI** (GitHub Actions),
  returning a `GhPipelineSource`; absent `gh` → an empty source so the skill degrades gracefully.
  With `gh` present but no GitHub remote it returns an `ops.UnavailablePipeline`, which **raises**
  `ops.SourceUnavailable` — report *unknown*, never "no deploys" (ADR 0095).
- **`connectors.alert_source()`** returns a **`GrafanaAlertSource`** when `GRAFANA_URL` is set
  (token via `GRAFANA_TOKEN`), else an empty source. **MCP-first:** if a Grafana MCP tool is
  available (find it with `ToolSearch`), prefer it and map its alerts onto `ops.Alert`; the REST
  `GrafanaAlertSource` is the deterministic fallback.
- Other providers (GitLab/CircleCI for pipelines; Datadog/PagerDuty for alerts) are added behind
  the **same** Protocols — no change to `deploy-watch` or `ops.deploy_status`.
- **Never commit credentials.** `gh` and Grafana use their own auth (env/MCP); any logging is
  redacted by the guardrails layer.
