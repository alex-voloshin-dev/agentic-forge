# Configuration

The plugin reads optional JSON config from two places, both validated against
[`schemas/config.schema.json`](../plugin/schemas/config.schema.json):

- **User-level** (cross-project): `~/.agentic-forge/config.json` — your personal defaults (ADR 0049).
- **Per-repo** (committed): `<repo>/.agentic-forge/config.json` — project-specific overrides.

**Precedence (lowest → highest):** built-in defaults < user-level file < per-repo file < env vars.
The two files deep-merge, so a repo overrides only the keys it sets and inherits the rest. All keys
are optional. A ready, schema-valid example with **every** key ships at
[`plugin/config.example.json`](../plugin/config.example.json) — copy it to either location and trim.

> These files are committed / home-local — **never** put secrets (API keys, tokens) in them. Use the
> env vars for secrets and one-off overrides.

## Keys

| Key | Type | Default | Effect |
|---|---|---|---|
| `diagnostics.enabled` | bool | `false` | Turn on the self-diagnostics log `.agentic-forge/diagnostics.jsonl` — guardrail denials, hook crashes, pipeline failures (ADR 0039). **This is "the logger."** |
| `subagent_budget.soft` | int ≥ 0 | `25` | Per-session subagent (`Task`) count at which the budget hook warns. |
| `subagent_budget.hard` | int ≥ 0 | `50` | Count at which the budget hook blocks further `Task` spawns. |
| `test_gate.skip` | bool | `false` | Skip the pre-commit test gate (the `commit_gate` hook). |
| `review.passes` | int ≥ 1 | `3` | The bounded review-loop budget N. |
| `external_reviewer.enabled` | bool | `true` | Enable the external reviewer pass — on by default, auto-invoked as an extra lens in `develop` + `product` (ADR 0042 / 0057). Degrades gracefully when the CLI is absent; set `false` to opt out (e.g. secret-bearing repos). |
| `external_reviewer.command` | string | `"codex"` | The reviewer executable name on PATH (a bare name, not a shell line). |
| `models` | object | `{}` | Per-role / skill / `router` model tiers (ADR 0043) — each value is a tier (`default` / `simple` / `cheap`) or a model id. **Affects the eval/dev CLIs only** (`dev/run_*_evals.py`, `dev/pr_watch.py`, `dev/ralph.py`) — live-session role routing is the gate-validated agent frontmatter (ADR 0046), which this key does not change. Empty = the runner's default model everywhere. See the [eval runbook](eval-runbook.md). |
| `pr_watcher.enabled` | bool | `false` | Enable the PR watcher's outward GitHub writes (ADR 0044/0045). |
| `pr_watcher.bot` | string | `"github-actions[bot]"` | The bot login whose review threads the watcher skips. |
| `pr_watcher.max_threads` | int ≥ 1 | `10` | Max review threads handled per run. |
| `pr_watcher.repos` | string[] | `[]` | `owner/name` repos the scheduled hourly job watches. |

## Env-var overrides

These win over both files (an empty value is ignored, so `export VAR=` can't clobber a file):

| Env var | Overrides |
|---|---|
| `AGENTIC_FORGE_DIAGNOSTICS` | `diagnostics.enabled` |
| `AGENTIC_FORGE_SUBAGENT_SOFT` | `subagent_budget.soft` |
| `AGENTIC_FORGE_SUBAGENT_HARD` | `subagent_budget.hard` |
| `AGENTIC_FORGE_SKIP_TEST_GATE` | `test_gate.skip` |

## Enabling the logger (example)

To turn the diagnostics log on for **every** project, put this in `~/.agentic-forge/config.json`:

```json
{ "diagnostics": { "enabled": true } }
```

…or set it for one repo only in `<repo>/.agentic-forge/config.json`, or once via
`AGENTIC_FORGE_DIAGNOSTICS=1`. Then read the log with
`python dev/diagnostics_digest.py --repo <path>`.

## Which Python do you need?

Two different answers, and conflating them cost a real user a debugging session:

- **Using the plugin (hooks, shipped skill scripts):** whatever `python3` is on PATH, **3.9 or
  newer**, with **no third-party packages**. The hook-reachable modules are stdlib-only at import
  time and every shipped file carries `from __future__ import annotations` (Tier-0 enforces this),
  so macOS CommandLineTools' pinned 3.9.6 works as-is — this is the field-verified baseline.
- **Developing the plugin** (running `dev/` CLIs, `pytest`, the eval gates): Python **≥ 3.11** plus
  the dev deps (`pip install -e .`) — that is what `pyproject.toml`'s `requires-python` describes.

Config is validated with `jsonschema` when it is installed. A guardrail hook may run under a bare
`python3` without it; in that case a committed config is loaded **unvalidated** (trusted) rather than
dropped, and every value is coerced defensively so resolution never crashes (ADR 0050). Install the
plugin's deps (`pip install -e .`) for schema validation and the knowledge-vault session injection.
