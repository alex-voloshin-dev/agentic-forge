# Pulling live alerts (connectors)

`incident-response` classifies severity and assembles the record. For a live incident, pull active
alerts instead of reading a scenario file (ADR 0025):

```
python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" alerts-active --environment production
```

It exits 1 when the source cannot answer, or there is none — report 'unknown', never 'no alerts'
(ADR 0094, 0104).
`${CLAUDE_PLUGIN_ROOT}` is the plugin's directory, the one holding `skills/`, and is not normally
set in a shell: if this file reached you unexpanded, use the path your skill's own commands show.

- **The alert source** is Grafana's REST API when `GRAFANA_URL` / `GRAFANA_TOKEN`
  are set. **MCP-first:** prefer a Grafana MCP tool (find it with
  `ToolSearch`) when present; the REST adapter is the deterministic fallback.
- **Alerts inform the flags, they don't bypass classification.** Read the alerts to decide the
  facts (a `critical` alert with no workaround → `outage`/`degraded`), then keep severity *derived*
  via `incident-classify`; use the result's `triage` to summarise counts for the timeline.
- Other alert providers (Datadog/PagerDuty) are added behind the same `AlertSource` Protocol — no
  change to the skill or the classification.
- Never commit credentials (env / MCP); logging is redacted by the guardrails layer.
