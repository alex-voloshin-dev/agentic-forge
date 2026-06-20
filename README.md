# agentic-forge

> Skill-centric, eval-driven Claude Code plugin for the full software lifecycle.

agentic-forge packages the way a team actually ships software — research, product,
architecture, UI/UX, planning, development, QA, deployment — as **workflow skills** that
Claude Code loads automatically when they are relevant. It is built on three commitments:

- **Standard-compliant.** Every skill follows the [Agent Skills](https://agentskills.io)
  open standard and validates with `skills-ref`.
- **Native to Claude Code.** Subagents, plan mode, git worktrees, review loops, and Ralph
  loops are used directly — not reimplemented.
- **Eval-driven.** No component ships without a contract and a numeric eval gate. See
  [`CLAUDE.md`](./CLAUDE.md) for the full rulebook.

## Status

Layer 0 (meta-core) is complete and green. Workflow domains are next — see the
[roadmap](docs/roadmap.md). The knowledge base is Layer 3 (not part of meta-core yet).

- [x] Repository skeleton, manifests, tooling
- [x] Tier-0 deterministic validator + tests
- [x] eval/contract schemas
- [x] hybrid eval-harness (on `skill-creator`)
- [x] `skill-factory` meta-skill
- [x] dogfood + CI

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
ruff check . && mypy plugin/lib dev       # lint + types
```

## Install (once published)

```text
/plugin marketplace add <this-repo>
/plugin install agentic-forge@agentic-forge
```
