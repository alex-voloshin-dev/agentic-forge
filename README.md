# agentic-forge

> Skill-centric, eval-driven Claude Code plugin for the full software lifecycle.

agentic-forge packages the way a team actually ships software — research, product,
architecture, UI/UX, planning, development, QA, deployment — as **workflow skills** that
Claude Code loads automatically when they are relevant. It is built on three commitments:

- **Standard-compliant.** Every skill follows the [Agent Skills](https://agentskills.io)
  open standard and validates with `skills-ref`.
- **Native to Claude Code.** Subagents, plan mode, git worktrees, review loops, and
  fan-out/fan-in are used directly — not reimplemented.
- **Eval-driven.** No component ships without a contract and a numeric eval gate. See
  [`CLAUDE.md`](./CLAUDE.md) for the full rulebook.

## Status

Layer 0 (meta-core) and Layer 1 (engine: roles, handoff, fan-out/review-loop/worktree
patterns) are complete and green; the six engine roles pass Tier-2. Layer 2 — the six-phase
SDLC spine (research → product → architecture → plan → develop → code-review) — is built and
proven end-to-end (Tier-3). Multi-stack support is built too — by-stack detection plus a
`*-patterns` pack for each of the nine registered stacks (Python, TypeScript, JavaScript, Go,
Rust, JVM, .NET, Ruby, PHP). The knowledge base (Layer 3) is built too — an Obsidian vault +
`knowledge` recall/capture skill + a session-start hook; only guardrails (Layer 4) remain. See
the [roadmap](docs/roadmap.md).

- [x] Repository skeleton, manifests, tooling
- [x] Tier-0 deterministic validator + tests
- [x] eval/contract schemas
- [x] hybrid eval-harness (on `skill-creator`)
- [x] `skill-factory` meta-skill
- [x] dogfood + CI
- [x] Layer 1 engine (minimal) — roles, handoff helper, patterns
- [x] agent Tier-2 eval runner (subscription / CI)
- [x] Layer 2 SDLC spine — six phase-workflow skills, proven end-to-end (Tier-3)
- [x] Layer 2 by-stack — detection + a `*-patterns` pack per registered stack (9 languages)

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

## Install (once published)

```text
/plugin marketplace add <this-repo>
/plugin install agentic-forge@agentic-forge
```
