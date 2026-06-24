# Wiring a real pipeline source (connectors)

`deploy-watch` assesses rollout health through the `ops.PipelineSource` / `ops.AlertSource`
seams. In a live repo, use a real connector instead of a recorded snapshot (ADR 0025):

```
python -c "
from agentic_forge import connectors, ops
pipeline = connectors.pipeline_source('OWNER/REPO')   # GhPipelineSource if gh is on PATH, else empty
print(ops.deploy_status(pipeline, ops.InMemoryAlerts({}), 'production'))
"
```

- **`connectors.pipeline_source(repo)`** auto-detects the **`gh` CLI** (GitHub Actions) and returns
  a `GhPipelineSource`; if `gh` is absent it returns an empty in-memory source so the skill
  degrades gracefully (reports "no pipeline source").
- **Alerts** await an `AlertSource` connector (a later phase, MCP-first for Datadog/PagerDuty).
  Until one is configured, pass an empty `ops.InMemoryAlerts({})` — health then reflects pipeline
  state only.
- Other CI providers (GitLab, CircleCI) are added behind the **same** `PipelineSource` Protocol —
  no change to `deploy-watch` or `ops.deploy_status`.
- **Never commit credentials.** `gh` uses its own auth; MCP servers handle theirs. Any logging is
  redacted by the guardrails layer.
