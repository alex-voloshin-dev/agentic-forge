# agentic-forge (Claude Code plugin)

A skill-centric, eval-driven plugin for the full software lifecycle. Skills express
*workflows* and auto-load by name + description; subagent roles execute; hooks enforce
guardrails. This directory is the installable plugin; project docs live one level up in
[`../docs/`](../docs/README.md) and the rulebook is [`../CLAUDE.md`](../CLAUDE.md).

## Install

Local (from a clone):

```bash
# In a Claude Code session, register this repo as a plugin marketplace:
/plugin marketplace add /path/to/agentic-forge
/plugin install agentic-forge

# …or load the plugin directly for one session:
claude --plugin-dir /path/to/agentic-forge/plugin
```

Confirm it loaded: ask "what skills are available?" or type `/` and look for the
`agentic-forge:` skills.

## Using it

Skills auto-load from what you ask — you don't call them by hand. For example:

- "Research how teams do X, then write a PRD" → `research` → `product`.
- "Plan and implement this feature, then review it" → `plan` → `develop` → `code-review`.
- "Audit these docs for contradictions and gaps" → `deep-review`.
- "Build me a new skill that does Y" → `skill-factory` (contract → evals → implementation → gate).

## What's inside

| Path | What it is |
| --- | --- |
| `skills/<name>/` | The skills — each a `SKILL.md` + `references/`, `assets/`, `scripts/`, `evals/evals.json`. |
| `agents/<name>.md` | Subagent roles skills delegate to (reviewer, software-engineer, architect, …), each with an eval contract. |
| `patterns/` | Engine pattern references (review loop, fan-out/fan-in, adversarial/ multi-aspect review, handoff, worktree). |
| `hooks/` | Guardrail + session-start hooks (`hooks.json` + Python scripts). |
| `lib/agentic_forge/` | Shared, importable, tested Python used by scripts and hooks. |
| `eval/` | Eval-harness docs + agent eval fixtures. |
| `schemas/` | JSON Schema for the `evals.json` contract. |

## Standard compliance

Every skill conforms to the [Agent Skills](https://agentskills.io) open standard and passes
the Tier-0 validator (`python ../dev/validate.py`). Claude Code extensions use only documented
optional frontmatter fields.

See [`../docs/README.md`](../docs/README.md) for architecture and decisions, and
[`../CONTRIBUTING.md`](../CONTRIBUTING.md) to build a component. Licensed under
[MIT](../LICENSE).
