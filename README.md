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

Early scaffolding. Layer 0 (meta-core) is under construction:

- [x] Repository skeleton, manifests, tooling
- [ ] Tier-0 deterministic validator + tests
- [ ] eval/contract schemas
- [ ] hybrid eval-harness (on `skill-creator`)
- [ ] `skill-factory` meta-skill
- [ ] dogfood + CI

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
