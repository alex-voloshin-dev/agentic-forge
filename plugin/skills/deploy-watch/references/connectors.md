# Wiring a real pipeline source (connectors)

`deploy-watch` assesses rollout health through the `ops.PipelineSource` / `ops.AlertSource`
seams. In a live repo, use a real connector instead of a recorded snapshot (ADR 0025):

```
python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" deploy-status --environment production --repo .
```

`--repo` is a checkout path or `OWNER/REPO`. `${CLAUDE_PLUGIN_ROOT}` is the plugin's directory, the
one holding `skills/`, and is not normally set in a shell: if this file reached you unexpanded,
use the path your skill's own commands show.

- **The pipeline source** takes a checkout **path** or an `owner/name` slug (a path
  is resolved through its `origin` remote) and auto-detects the **`gh` CLI** (GitHub Actions);
  absent `gh`, `gh` present but no GitHub remote, or `gh` failing, the result carries
  `unavailable.pipeline` and a `pipeline` of `unknown` — report *unknown*, never "no deploys"
  (ADR 0095, 0104). Health comes from the latest run of each workflow, on any branch.
- **The alert source** is Grafana's REST API when `GRAFANA_URL` is set
  (token via `GRAFANA_TOKEN`). With none, the pipeline's reading stands and the result carries
  `unavailable.alerts`: say the alerts were not read, because that is not no alerts. A source that is set and fails reads `unknown`. **MCP-first:** if a Grafana MCP tool is
  available (find it with `ToolSearch`), prefer it: write its alerts to a file as
  `[{"severity", "summary", "source"}]` and pass them with the live pipeline:
  `python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" deploy-status --environment production --alerts-json <file> --repo .`.
  The REST adapter is the deterministic fallback. `--snapshot` is a whole recorded state, deploys
  and alerts, and takes neither `--repo` nor `--alerts-json`: an alerts-only file there would read
  as no deploys, so as healthy. A record whose `environment` is another one is left out, and a
  file where every record is for another one is refused, naming them.
- Other providers (GitLab/CircleCI for pipelines; Datadog/PagerDuty for alerts) are added behind
  the **same** Protocols — no change to `deploy-watch` or to the assessment.
- **Never commit credentials.** `gh` and Grafana use their own auth (env/MCP); any logging is
  redacted by the guardrails layer.
