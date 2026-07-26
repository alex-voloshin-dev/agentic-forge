---
type: release
feature: agentic-forge-2026.7.10
status: final
version: 2026.7.10
date: 2026-07-26
changelog:
  - "Fixed: the plugin ships its runtime CLIs and stops writing state into the user's repository (ADR 0072) — `run_scheduled.py`, `pr_watch.py` and `external_review.py` move to `plugin/bin/` (only `plugin/` ships, so thirteen shipped files had pointed users at `dev/` paths their install does not contain), and diagnostics, audit, schedule state and the PR-watch queue resolve through one user-level `state_root()` keyed by repo slug, with a legacy read-fallback and an opt-in `state.in_repo`"
  - "Fixed: subagent dispatch is containment (ADR 0073) — never `fork` for recon that must not act (a fork inherits the standing directive and opened a real PR under a READ-ONLY prompt), `isolation: \"worktree\"` when a subagent touches files, review lenses only at the top level; output caps plus \"a degenerate lens is failed, not clean\" and the resume anti-pattern; and a self-report is a claim to cross-check, with uncertainty a valid answer"
  - "Added: four field traps the plugin never warned about (ADR 0074) — worktree hazards (two silently corrupt the main checkout), build/container contention misread as regression, semantic conflicts between cleanly-merging PRs on one state transition, and a two-strike stop rule for speculative fixing"
  - "Added: the field report's P2 batch (ADR 0075) — blocking bare `printenv`/`env`/`set` on a remote host (a prefix filter matched a credential and printed it), read the original before a behaviour-changing corrective, no mutating requests to production during QA, a decision record is an intent not a deployment, shared-working-tree hygiene, and summaries follow the user's language while artifacts follow the project's"
  - "Added: a warning-only pre-merge preflight hook (ADR 0076) — another worktree holding the base branch, or a local base ahead of upstream, are named before `gh pr merge` instead of after it fails"
  - "Fixed: eval runs no longer inherit the operator's own config (ADR 0077) — `--setting-sources project`, after graded artifacts turned up in the maintainer's personal language; Tier-2 numbers are now machine-independent"
  - "Added: `logs.enabled` (ADR 0078) — the audit trail was the one state writer with no off switch; default stays on"
  - "Added: two Tier-0 contract gates (packaging + state boundary) and a doc-sync warning for an ADR nothing cites, which found 11 orphans of 78"
breaking: []
---

# Release 2026.7.10

The plugin stops writing into repositories it does not own — and stops promising commands it does
not ship.

## Why this one matters more than its size suggests

Two defects here were **invisible from inside this repository**, because it is simultaneously the
plugin's source and its test subject. Both were found by running the plugin on a real, unrelated
production project.

**It shipped commands that did not exist.** `marketplace.json` declares `"source": "./plugin"`, so
only `plugin/` reaches an installed user — yet three *runtime* entry points lived in `dev/`:
`run_scheduled.py` (the scheduler's only entry point), `pr_watch.py` (the sole production caller of
the merge rails) and `external_review.py` (invoked by seven skills). Thirteen shipped files told
users to run paths their installation does not contain. The autonomous capabilities of 2026.7.6–7.9
were, for every user but us, unreachable.

**It wrote its own state into other people's repositories.** The audit log grew on every tool call
under `<repo>/.agentic-forge/`. A production user moved 8.1 MB of it out and watched the directory
**reappear within 16 seconds** — recreated by the hook recording the very `mv` that emptied it.
Generated state now lives at `~/.agentic-forge/state/<repo-slug>/`; the committed `config.json`
stays where it belongs. Configuration is the project's, state is the runtime's.

## What else came from the field

Ten more findings from the same report, all shipped: the `fork` that ignored a READ-ONLY prompt and
opened a real PR; audit lenses that died at the structured-output step while the run reported
success; a self-report that fabricated a user approval; four worktree traps; parallel-build
contention misread as regression; two PRs whose guards merged cleanly and halted production
together; and a stop rule for the third speculative fix.

One code-level security fix: a bare `printenv` on a remote host is now blocked, after a
prefix-filtered dump matched `…_CRUX_API_KEY` and printed it into a transcript.

## What this release found out about itself

The work was reviewed against its own standards, and that pass was more productive than the code:

- **Both field fixes had no gate.** They were fixed once with nothing preventing their return — and
  the test fixture that isolates state would have *hidden* an in-repo-write regression rather than
  catching it. Two structural contract tests now pin them, mutation-checked in both directions.
- **Every eval this project ever ran was contaminated.** Graded artifacts came back in the
  maintainer's personal language, traced to `~/.claude/CLAUDE.md` reaching the run. Tier-2 numbers
  were not comparable across machines. Fixed with `--setting-sources project`.
- **A new eval case could not measure what it claimed.** Added with ADR 0073, never run, it failed
  on first execution; isolated it scored `0.0 / 0.5 / 1.0 / 0.5` — it measured how talkative a run
  happened to be. A Tier-2 skill eval grades text, never tool calls.
- **11 ADRs of 78 were unreachable** from the rules they justify, including two written that day.
  Tier-0 now warns on it.

## Verification

- **Tier-0**: `validate.py` (0 errors, **0 warnings**), `pytest` (coverage ~98%), `ruff`, `mypy` —
  clean.
- **Tier-2 live**, under the shipped configuration: `deep-review` **PASS** (mean 0.950, sd 0.052,
  lower bound 0.898); `software-engineer` **PASS** (1.000, sd 0.000).
- **Tier-1 not re-run**: no skill `description` changed, which is what it measures.

## Upgrading — read this if you ran an earlier version

Reads fall back to an existing in-repo file, so a repo already running the plugin keeps one
continuous history and **no migration is required**. But if you moved the directory out by hand,
the new location is keyed by a **digest of the absolute path**, not by the repo name:

```bash
python3 -c "import hashlib,pathlib;p=pathlib.Path('.').resolve();print(f'{p.name}-{hashlib.sha256(str(p).encode()).hexdigest()[:8]}')"
# -> move your data to ~/.agentic-forge/state/<that>/
```

Run it from the main checkout, not a worktree. `state.in_repo: true` restores the old layout.

## Not validated

- **The PR watcher still has no real-PR run** — a debt since ADR 0045, now carrying the project's
  own document delivery.
- **No downstream install has exercised** the `plugin/bin` move or the state relocation.
- **Adherence** to the subagent-type rule is ungated; only its articulation is. A Tier-2 skill eval
  cannot see tool calls.
- **Audit-log volume is unaddressed**: 8.1 MB in ten days on one repo extrapolates to ~300 MB/year,
  and rotation evidently does not keep up. A gate is not a retention policy; the right bound needs
  its own measurement.
- The orphaned-ADR check is a **warning**, so a future orphan will not block a merge.
