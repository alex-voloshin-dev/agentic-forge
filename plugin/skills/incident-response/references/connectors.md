# Pulling live alerts (connectors)

`incident-response` classifies severity and assembles the record. For a live incident, pull active
alerts instead of reading a scenario file (ADR 0025):

```
python -c "
from agentic_forge import connectors, ops
alerts = connectors.alert_source().active_alerts('production')  # GrafanaAlertSource if GRAFANA_URL set
print(alerts); print(ops.triage_alerts(alerts))
"
```

- **`connectors.alert_source()`** returns a `GrafanaAlertSource` when `GRAFANA_URL` / `GRAFANA_TOKEN`
  are set, else an empty source. **MCP-first:** prefer a Grafana MCP tool (find it with
  `ToolSearch`) when present; the REST adapter is the deterministic fallback.
- **Alerts inform the flags, they don't bypass classification.** Read the alerts to decide the
  facts (a `critical` alert with no workaround → `outage`/`degraded`), then keep severity *derived*
  via `ops.classify_incident(...)`; use `ops.triage_alerts` to summarise counts for the timeline.
- Other alert providers (Datadog/PagerDuty) are added behind the same `AlertSource` Protocol — no
  change to the skill or `ops.classify_incident`.
- Never commit credentials (env / MCP); logging is redacted by the guardrails layer.
