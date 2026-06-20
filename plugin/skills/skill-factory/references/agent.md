# Authoring a subagent

A subagent is a Markdown file `plugin/agents/<name>.md` with YAML frontmatter and a
system-prompt body. Skills delegate to it via `context: fork` + `agent: <name>` or via
the `Task` tool. Users do not call agents directly — keep the plugin skill-centric.

## When a subagent (not a skill)

Create a subagent only when you need at least one of:

- **Isolation** — a clean context window for a sub-task (research, grading, review).
- **A different model or effort** than the main session.
- **A restricted toolset** — e.g. read-only exploration, or no `AskUserQuestion` for an
  autonomous loop.

Otherwise prefer a skill. A subagent with no clear task is dead weight.

## Frontmatter

- `name` — file name without extension; same naming rules as skills.
- `description` — when the orchestrator should delegate here; keywords matter.
- `tools` — the allowed tool set (omit to inherit). Narrow it to the role.
- `model` — `inherit` or a specific model when the role benefits from it.

## Body

The body is the agent's system prompt: its role, the contract for what it returns
(prefer a structured, parseable result), and its boundaries. Keep it focused; an agent
that returns an unstructured essay is hard to compose in a fan-out/fan-in pattern.

## Evals

Agents are gated by Tier 2 on a fixed task set: run the role on representative tasks and
grade outputs against assertions, N>=5, lower-bound pass-rate >= threshold. Put the
contract and thresholds in `plugin/agents/evals/<name>.evals.json` (same superset
schema; `component.type: "agent"`).

## Checklist

- Justified against the "when a subagent" test — not a skill in disguise.
- Tools narrowed to the role; return contract explicit.
- evals.json with `component.type: agent` and thresholds.
