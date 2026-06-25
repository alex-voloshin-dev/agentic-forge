# agentic-forge

> Skill-centric, eval-driven Claude Code plugin for the full software lifecycle.

agentic-forge packages the way a team actually ships software — research, product,
architecture, UI/UX, planning, development, QA, deployment — as **workflow skills** that
Claude Code loads automatically when they are relevant. It is built on three commitments:

- **Standard-compliant.** Every skill follows the [Agent Skills](https://agentskills.io)
  open standard and passes the in-repo `python dev/validate.py` (a `skills-ref`-style check; the
  external `skills-ref` CLI is not required).
- **Native to Claude Code.** Subagents, plan mode, git worktrees, review loops, and
  fan-out/fan-in are used directly — not reimplemented.
- **Eval-driven.** No component ships without a contract and a numeric eval gate. See
  [`CLAUDE.md`](./CLAUDE.md) for the full rulebook.

## Status

All five layers are in place and gated (Tier-0 + the eval pyramid green at every commit):

- **L0 meta-core** — `skill-factory`, the eval harness, the shared `lib/`, the Tier-0 validator.
- **L1 engine** — six subagent roles (reviewer, grader, software-engineer, architect,
  security-engineer, qa-engineer) + handoff schemas + the fan-out / multi-aspect-review /
  adversarial-review / review-loop / worktree patterns.
- **L2 workflow skills** — the six-phase SDLC spine (research → product → architecture → plan →
  develop → code-review), proven end-to-end (Tier-3), stack-parametric via `stacks.py` + nine
  `*-patterns` packs; plus quality/ops (qa-test-strategy, security-review, deploy-watch,
  incident-response, release), marketing, and ux-design / repo-onboarding.
- **L3 knowledge base** — an Obsidian vault + the `knowledge` recall/capture skill + a
  session-start hook.
- **L4 guardrails & ops** — security / test-gate / logging / budget hooks, plus scheduling &
  observability (a declarative job registry + audit-log digest + cron CI).

Real provider connectors (GitHub Actions, Grafana, live web research) plug into the ops/marketing
seams. See the [roadmap](docs/roadmap.md) and [CHANGELOG](CHANGELOG.md).

## Install

```text
# From a local clone (works today):
/plugin marketplace add /path/to/agentic-forge       # repo root — holds .claude-plugin/marketplace.json
/plugin install agentic-forge@agentic-forge
# …or point Claude Code straight at the plugin dir:
claude --plugin-dir /path/to/agentic-forge/plugin

# Once published to GitHub:
/plugin marketplace add <owner>/agentic-forge
/plugin install agentic-forge@agentic-forge
```

## Using the plugin

You don't invoke skills by hand — they **auto-load by description** when your request matches.
Describe the work and the right skill activates and writes its handoff artifact. For example:

- "Research options for full-text search" → **research** → a `research-brief`.
- "Plan the work for this design" → **plan** → `plan.md`.
- "Implement the current plan step" → **develop** (worktree → software-engineer → review loop → QA).
- "Review this diff before I merge" → **code-review** → an approve/changes verdict.
- "What did we decide about caching?" → **knowledge** (recalls from the vault).
- "Cut a release" → **release**; "is the prod deploy healthy?" → **deploy-watch**.

To force a specific skill, type `/agentic-forge:<skill>` (e.g. `/agentic-forge:release`).

## Skills

The `*-patterns` packs (python, typescript, javascript, go, rust, jvm, dotnet, ruby, php) +
`engineering-standards` load on demand for the repo's detected stack. The on-listing skills:

| Skill | What it does |
| --- | --- |
| `research` | Investigate options / prior art before speccing → `research-brief` |
| `product` | Turn research into a PRD (goals, metrics, acceptance) |
| `architecture` | Technical design + ADRs → `tech-design` |
| `plan` | Dependency-ordered work plan → `plan.md` |
| `develop` | Implement a plan step in a worktree (code + review loop + QA) |
| `code-review` | Multi-aspect review of a diff → approve/changes verdict |
| `deep-review` | Deep, adversarial, multi-perspective audit |
| `qa-test-strategy` | Plan what & how to test → `test-strategy` |
| `security-review` | Dedicated security audit → `review` |
| `deploy-watch` | Assess rollout health from CI/alerts → `deploy-status` |
| `incident-response` | Triage + classify severity (sev1–4) → `incident` |
| `release` | Semver bump + changelog from commits → `release` |
| `marketing` | Market/competitor research, GTM, content (evidence-cited) |
| `ux-design` | User flows, screens/states, accessibility → `ux-spec` |
| `repo-onboarding` | Analyze an unfamiliar repo + seed the knowledge vault |
| `knowledge` | Recall/capture durable project knowledge (Obsidian vault) |
| `skill-factory` | Create new components contract-first, evals-first |

## Documentation

Full docs live in [`docs/`](docs/README.md): [product vision](docs/product/vision.md),
[architecture](docs/architecture/overview.md),
[meta-core guide](docs/architecture/meta-core.md),
[decision records](docs/architecture/decisions/README.md), and the
[roadmap](docs/roadmap.md). Change history is in [CHANGELOG.md](CHANGELOG.md).

## Develop

```bash
uv venv && uv pip install -e ".[dev]"   # or: pip install -e ".[dev]"
python dev/validate.py                   # Tier-0 gate
pytest                                    # unit tests
ruff check . && mypy plugin/lib plugin/hooks dev   # lint + types
```

## License

MIT — see [`LICENSE`](LICENSE).
