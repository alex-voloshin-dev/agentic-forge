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

## Using it across the SDLC

You don't call skills by hand — you **describe intent**, the matching phase-skill activates,
does the work (often by fanning out to subagents), and writes a **handoff artifact** the next
phase reads. Spine artifacts land under `docs/sdlc/<feature>/`; durable knowledge lands in
`docs/knowledge/`. Everything is plain Markdown — committable, reviewable, and picked up by the
next phase, so the lifecycle is auditable rather than hidden in chat.

```
  idea
   │
   ▼
 research ─▶ product ─▶ architecture ─▶ plan ─▶ develop ⇄ code-review ─▶ merge
  brief       prd       tech-design     plan     code        review
                                                  ▲   ▲
                                qa-test-strategy ─┘   └─ security-review
                                 test-strategy            review

 after merge ─▶ release ─▶ deploy-watch ─▶ incident-response
                 release     deploy-status     incident

 always-on ─ knowledge (recall/capture → docs/knowledge/) · guardrail hooks (test-gate + security on every commit)
 new repo? ─ repo-onboarding maps the code and seeds the vault first
```

### Ship a feature end to end

Each line is roughly what you'd type; the arrow shows the skill that activates and the artifact
it writes.

```
"Research how task apps do priorities, then we'll spec it"
      → research          → docs/sdlc/task-priorities/research-brief.md
"Turn that brief into a PRD"
      → product           → prd.md  (goals · non-goals · metrics · acceptance)
"Design the architecture"
      → architecture      → tech-design.md + ADRs
"Plan the work"
      → plan              → plan.md (dependency-ordered tasks + checkpoints)
"Plan what to test"          (any time around build)
      → qa-test-strategy  → test-strategy.md
"Implement step 1"
      → develop           → worktree → code + tests → multi-aspect review ⇄ fixes → QA hardening
"Review the branch before I merge"
      → code-review       → review.md  (approve / changes)
— merge —
"Cut the release"            → release           → version bump + changelog
"Is the prod deploy healthy?"→ deploy-watch      → deploy-status
"Production is down"         → incident-response → incident (sev1–4) + postmortem
```

Throughout, `knowledge` recalls and saves decisions, and the guardrail hooks gate every commit.

### Two ways in

- **New feature** — start at `research` (or jump straight to `product` if you already have a
  brief). Each phase hands off to the next.
- **Existing / unfamiliar repo** — start at `repo-onboarding`: it maps the code and seeds the
  knowledge vault, which then enriches every later phase.

You can enter at any phase — a skill doesn't require the previous artifact to exist. To force
one, type `/agentic-forge:<skill>` (e.g. `/agentic-forge:release`).

## Skills by stage

The `*-patterns` packs (python, typescript, javascript, go, rust, jvm, dotnet, ruby, php) and
`engineering-standards` load on demand for the repo's detected stack — they don't appear in the menu.

**Frame & design**
- `research` — investigate options / prior art before speccing → `research-brief`
- `product` — turn a brief into a PRD (goals, metrics, acceptance) → `prd`
- `ux-design` — user flows, screens/states, accessibility → `ux-spec`
- `architecture` — technical design + ADRs → `tech-design`
- `marketing` — market/competitor research, GTM, content, evidence-cited → `market-brief` / `marketing-strategy`

**Build & verify**
- `plan` — dependency-ordered work plan → `plan`
- `develop` — implement a plan step in a worktree (code + review loop + QA)
- `code-review` — multi-aspect review of a diff → approve/changes `review`
- `deep-review` — deep, adversarial, multi-perspective audit of docs, a design, or code
- `qa-test-strategy` — plan what & how to test → `test-strategy`
- `security-review` — dedicated security audit → `review`

**Ship & operate**
- `release` — semver bump + changelog from commits since the last tag → `release`
- `deploy-watch` — assess rollout health from CI/alerts → `deploy-status`
- `incident-response` — triage + classify severity (sev1–4) + postmortem → `incident`

**Cross-cutting**
- `knowledge` — recall/capture durable project knowledge in the Obsidian vault
- `repo-onboarding` — analyze an unfamiliar repo + seed the vault → `onboarding`
- `skill-factory` — create new components contract-first, evals-first

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
