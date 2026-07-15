# Contributing to agentic-forge

Thanks for contributing. This project has a written constitution — read it first.

- **[`CLAUDE.md`](CLAUDE.md)** is the rulebook (the non-negotiable principles). It overrides
  any default behaviour, for humans and agents alike.
- **[`docs/`](docs/README.md)** is the source of truth for intent and design (vision,
  architecture, ADRs, roadmap). Plan a change there before implementing it.

This file is the short operational guide: how to set up, build a component, and pass the gate.

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). For security issues,
do **not** open a public issue — follow [SECURITY.md](SECURITY.md).

## Setup

```bash
git clone <repo> && cd agentic-forge
uv venv && uv pip install -e ".[dev]"     # or: pip install -e ".[dev]"
```

The `claude` CLI is needed only to run the live LLM evals (Tier 1–2); see the
[eval runbook](docs/eval-runbook.md).

## The one rule: contract → evals → implementation → gate

No component is built before its contract and its eval set exist. Order is always:

1. **Contract** — purpose, triggers, inputs/outputs (write it in `docs/` for anything
   non-trivial; record significant choices as an [ADR](docs/architecture/decisions/README.md)).
2. **`evals/evals.json`** — the numeric thresholds that define "done".
3. **Implementation** — the skill body / agent / script.
4. **Gate** — pass Tier 0 (and the higher tiers the component declares).

Use the **`skill-factory`** skill to scaffold a component the right way — it refuses to write
a body before the evals exist. Load the plugin (`claude --plugin-dir plugin`) and describe
what you want to build.

## The gate (run before every commit)

Tier 0 is static and always blocks. Run it locally — CI runs the same:

```bash
python dev/validate.py                                   # frontmatter, body ≤500 lines, refs, evals exist
pytest -q --cov=agentic_forge --cov-fail-under=80        # tests + coverage ≥ 80%
ruff check .                                              # lint
mypy plugin/lib plugin/hooks dev                          # types
```

All four must be green. The higher tiers (Tier-1 trigger, Tier-2 quality, Tier-3 E2E) are
cost-gated and run on demand — see the [eval runbook](docs/eval-runbook.md) for how to run
them on your Claude subscription. Never make a gate pass by **lowering a threshold or dropping
an assertion** — fix the component, or make the eval fairer (see
[ADR 0020](docs/architecture/decisions/0020-tier2-inspection-gradeable-assertions.md)).

## Documentation discipline (same unit of work)

Any change that adds, changes, or removes functionality MUST, in the same change:

1. add a [`CHANGELOG.md`](CHANGELOG.md) entry (Added / Changed / Fixed / Removed);
2. update the affected docs under `docs/`;
3. record any significant decision as an ADR in `docs/architecture/decisions/`;
4. explain *how* it works, not just that it exists.

## Editing rules (from `CLAUDE.md`)

- All persisted content (skills, code, comments, docs) in **English**.
- `SKILL.md` body **≤ 500 lines**; push depth into `references/` (one level deep).
- **Python only** for scripts — no shell scripts; everything under `pytest`. Skill-specific
  executables live in `skills/<name>/scripts/`; shared, importable code in
  `plugin/lib/agentic_forge/`.
- Use runtime path variables (`${CLAUDE_SKILL_DIR}` / `${CLAUDE_PLUGIN_ROOT}`); never absolute
  user paths.
- Keep the always-on skill listing small and sharply described (router discipline) — depth
  goes in `references/`, loaded on demand.

## Pull requests

- Keep the Tier-0 gate green; include the CHANGELOG + docs/ADR updates in the same PR.
- If you touched a gated component, note the achieved eval numbers (and the model) in the
  CHANGELOG, per the eval-loop guide.
- Add the **`eval`** label to run the cost-gated Tier-1/2 jobs in CI.

## Cutting a release

Releases are versioned by **CalVer** `<year>.<month>.<inc>` — e.g. `2026.7.1`; the inc restarts
each month, no zero-padding, and breaking changes are flagged in the CHANGELOG, never encoded in
the version ([ADR 0055](docs/architecture/decisions/0055-calver-versioning.md)). The next version
is computed, not invented: `release.next_calver(current, year=, month=)` with today's UTC date
(the `release` skill does this for you).

`master` is protected by a repository ruleset that is **not** visible in the tree, so know it
here: direct pushes are rejected; every change lands via a **PR** with the **"Tier 0 (static
gate)"** status check green; history is **linear** (rebase/squash — merge commits are blocked);
auto-merge is disabled. Because the rebase merge **rewrites commit SHAs**, the tag must be created
*after* the merge, on the merged commit — never tag-and-push before merging.

The flow (precedent: PR #3, `v2026.7.1`):

1. On a branch: the work commit(s), then a `Release <calver>` commit — bump
   `plugin/.claude-plugin/plugin.json`, cut the `CHANGELOG.md` `[<calver>]` section (keep a fresh
   `[Unreleased]` above), and add the release handoff artifact
   (`docs/sdlc/agentic-forge-<calver>/release.md`, header valid per
   `handoff.validate_header(..., expected_type="release")`).
2. Run the full gate (the four commands above), push the branch, open the PR.
3. Wait for the Tier-0 check (`gh pr checks <n> --watch`), then `gh pr merge <n> --rebase`.
4. Fetch; confirm the merged tip is content-identical to your local release commit
   (`git rev-parse <local>^{tree}` equals `<merged>^{tree}`).
5. Tag the **merged** commit: `git tag -a v<calver> <merged-sha> -m "…"` and push the tag.
6. Clean up: `git reset --hard origin/master`; delete the release branch (local needs `-D` —
   after a rebase merge git can't see it as merged).
