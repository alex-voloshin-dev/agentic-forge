# 0072 — Runtime CLIs ship with the plugin; runtime state lives at the user level

**Status:** Accepted (implemented)
**Date:** 2026-07-26
**Supersedes/amends:** the path claims in 0024 (scheduling state), 0039 (diagnostics log),
0068/0069 (the auto-watch queue), and the `dev/` CLI references in 0042/0044/0045.

## Context

Field evidence from a production repo running the plugin (`2026-07-26-f4ai-field-report.md`,
findings **AF-06** and **AF-05**) surfaced two defects that only appear *outside* this repository.
Both had been invisible here because this repo is simultaneously the plugin's source checkout and
its test subject — a class of blind spot ADR 0058's earlier field round also exposed.

### AF-06 — the plugin promised commands it does not ship

`marketplace.json` declares `"source": "./plugin"`. Only `plugin/` reaches an installed user. Yet
three **runtime** entry points lived in `dev/`:

- `run_scheduled.py` — the external clock's only entry point (ADR 0024). Without it the scheduled
  drain, the audit digest and the PR-watch queue (ADR 0068) can never run.
- `pr_watch.py` — the watcher CLI, the *only* production caller of the merge rails (ADR 0067 §1).
- `external_review.py` — the external-reviewer seam (ADR 0042), referenced by seven skill bodies.

Thirteen shipped files and the installation docs instructed users to run paths that do not exist in
their installation. The plugin's most autonomous capabilities were, for every user but us,
undeliverable.

### AF-05 — the plugin wrote its own state into the user's repository

Four runtime files were written under `<user-repo>/.agentic-forge/`: `diagnostics.jsonl`,
`audit.jsonl`, `schedule-state.json`, `pr-watch-queue.json`. Three consequences, ordered by how
much they cost:

1. **It violates a standing user policy** that agent state and memory live at the user/home level
   and never inside a project, subproject or worktree.
2. **It pollutes repositories the plugin does not own.** The audit log grows on *every* tool call.
   Untracked files appear in `git status`; a `git add -A` in a downstream repo commits them.
3. **It leaks across boundaries.** Audit and diagnostics records describe the *session*, not the
   project. A repo is the wrong key for them and the wrong place to store them.

The distinction that resolves it: **configuration is the project's, state is the runtime's.**
`<repo>/.agentic-forge/config.json` is authored, reviewed and committed by the repo's owner — it
stays. Everything the plugin *generates* moves out.

## Decision

### 1. `plugin/bin/` — the shipped runtime CLI directory

`run_scheduled.py`, `pr_watch.py` and `external_review.py` move to `plugin/bin/`. `dev/` keeps only
maintainer and eval CLIs (`validate.py`, the eval runners, `audit_digest.py`,
`diagnostics_digest.py`, `ralph.py`, `sync_models.py`), which no installed user needs.

The rule that decides where a CLI belongs: **if any shipped artifact — a skill body, a hook, a
pattern, a doc a user follows — tells someone to run it, it ships.** All three qualified: skills
invoke `external_review.py`, the scheduling contract requires `run_scheduled.py`, and `pr_watch.py`
is what `run_scheduled.py` spawns.

Shipped CLIs resolve their imports from the plugin tree, not the repo:

```python
_HERE = Path(__file__).resolve().parent   # plugin/bin
_PLUGIN_ROOT = _HERE.parent               # plugin/
sys.path.insert(0, str(_PLUGIN_ROOT / "lib"))
```

They may import `agentic_forge` and the standard library, nothing else — verified, and the reason
`audit_digest.py` (which imports maintainer-side helpers) stayed behind. References in shipped files
use `${CLAUDE_PLUGIN_ROOT}/bin/<name>.py`; references in this repo's own docs use `plugin/bin/…`.

### 2. `diagnostics.state_root()` — one place that answers "where does state go?"

```python
def state_root(cwd: Path) -> Path:
    root = main_repo_root(cwd)                  # worktree -> its main repo, unchanged
    if settings.resolve(root).state_in_repo:    # opt-in escape hatch
        return root / ".agentic-forge"
    base = os.environ.get("AGENTIC_FORGE_STATE_HOME")
    home = Path(base) if base else Path.home() / ".agentic-forge"
    return home / "state" / repo_slug(root)     # "<dirname>-<sha256(abspath)[:8]>"
```

All four state files resolve through it. Three properties are load-bearing:

- **The worktree rule survives.** `main_repo_root` still collapses a worktree to its main repo, so
  every worktree of a project shares one state stream (ADR 0039's invariant, now expressed as
  "one slug", not "one directory in the checkout").
- **The slug is path-keyed, not name-keyed.** Two checkouts of the same repository are two
  projects; `sha256(absolute path)[:8]` keeps them apart without the collisions a bare directory
  name would produce.
- **Reads fall back to the legacy location.** `existing_state_file(cwd, filename, legacy_rel)`
  returns the in-repo file *if it already exists*, so a repo that has been running the plugin keeps
  one continuous history instead of silently starting a second one. New repos only ever write to
  the state root. No migration step, no data loss, and the fallback can be dropped later.

### 3. `state.in_repo` — an opt-in, off by default

Some users *want* the audit trail inside the project (a shared CI checkout, a compliance
requirement). `{"state": {"in_repo": true}}` restores the old layout. Off by default: the safe
behaviour must be the one you get without reading the docs.

`AGENTIC_FORGE_STATE_HOME` relocates the root; its first purpose is hermetic tests — an autouse
`conftest` fixture points it at a `tmp_path`, so the suite can no longer write into the developer's
real `$HOME`, which it would otherwise now do.

## Consequences

- **The plugin no longer writes into repositories it does not own.** A fresh install produces no
  untracked files; `git status` in a downstream repo stays clean.
- **A user's installation can actually run the scheduler, the watcher and the external reviewer.**
  The autonomous capabilities of 2026.7.6–2026.7.9 become reachable for the first time.
- **Diagnostics and audit are now per-user, keyed by project** — which matches what they record.
  Collecting a bundle across projects is a directory listing rather than a repo crawl.
- **A `dev/`-path habit is now a bug.** The inventory in `CLAUDE.md` and `docs/architecture/meta-core.md`
  splits the two directories explicitly and states which one ships.
- **The state root is not portable between machines.** It is keyed by absolute path, so a repo moved
  or re-cloned elsewhere starts a fresh stream. Accepted: this state is diagnostic, not precious,
  and the alternative (a repo-identity key, e.g. the origin URL) fails for repos with no remote.
- **Not validated in the field.** The move is covered by the suite and by a manual run of both
  relocated CLIs from their new location, but no downstream install has exercised it yet — the same
  standing gap the PR watcher carries.
