# Handoff to Claude Code CLI

> **Status: completed (historical).** The L0→CLI handoff is done and Stage 1 has shipped
> (engine roles, handoff helper, patterns; the four roles pass Tier-2). Kept as a record of
> the handoff; for current work see the [roadmap](roadmap.md).

This repo's design, planning, and documentation were done in Cowork. Implementation from
Stage 1 onward should continue in the **Claude Code CLI**, where the plugin actually runs:
skills auto-load, subagents/forking and worktrees work, hooks fire, and the `skill-creator`
eval loop (Tier 1–2) can run. Use Cowork again for future design/research sessions.

## 1. Commit the current state

Cowork's sandbox could not clear git lock files. On your machine:

```bash
cd ~/code/agentic-forge
rm -f .git/*.lock
git add -A
git commit -m "L0 meta-core + docs + two review passes"
```

## 2. Set up the toolchain

```bash
cd ~/code/agentic-forge
uv venv && uv pip install -e ".[dev]"      # or: pip install -e ".[dev]"
```

## 3. Verify the Tier-0 gate (should be green)

```bash
python dev/validate.py
pytest -q --cov=agentic_forge --cov-fail-under=80
ruff check .
mypy plugin/lib dev
```

Expected: validator clean, tests pass, coverage ≥ 80% (currently ~97.6%), ruff/mypy clean.

## 4. Wire up the eval engine and load the plugin

Inside `claude`:

```text
/plugin marketplace add anthropics/claude-plugins-official
/plugin install skill-creator@claude-plugins-official
/reload-plugins
```

Load this plugin in a session:

```bash
claude --plugin-dir ~/code/agentic-forge/plugin
```

Confirm `skill-factory` is available: ask "What skills are available?" or type `/` and look
for `agentic-forge:skill-factory`.

## 5. Continue with Stage 1

**Done — Stage 1 has shipped.** The starter prompt below is the historical kickoff; for the
next stage see [roadmap.md](roadmap.md).

Everything needed is already on disk and portable: `CLAUDE.md` (the rules),
`docs/architecture/engine.md` (the Stage 1 design), `docs/roadmap.md` (the plan),
`docs/architecture/decisions/` (ADRs), `CHANGELOG.md`.

Starter prompt for the CLI session:

```text
Implement Stage 1 (engine foundations) following docs/architecture/engine.md and
ADR 0009. Build the four roles (reviewer, grader, implementer, architect) via the
skill-factory process (contract -> evals -> implementation -> gate), add
lib/agentic_forge/handoff.py with per-type artifact header schemas and tests, and write
the pattern references (review loop, worktree, handoff). Keep the Tier-0 gate green and
follow the documentation discipline in CLAUDE.md (CHANGELOG + docs updates per change).
```

## 6. Keep the discipline

- Contract → evals → implementation → gate, for every component.
- Update `CHANGELOG.md` and the relevant `docs/` files in the same change (see CLAUDE.md).
- Run `python dev/validate.py` and `pytest` before each commit.

## When to come back to Cowork

Design and research for the next stages, generating documents, interactive decision
questions, and reviewing artifacts. Bring conclusions back into `docs/` so the CLI side
stays the source of truth for implementation.
