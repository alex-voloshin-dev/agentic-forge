# taskstore (fixture target-repo)

A tiny, real Python library used as the **target repository** for the Stage 2 SDLC-spine
end-to-end scenario. The spine *will* operate on an **isolated copy** of this repo (never the
fixture itself), carrying the feature in `FEATURE_REQUEST.md` through its phases and writing
handoff artifacts into `docs/sdlc/<feature-slug>/` in that copy.

Status: the Tier-3 scenario runner that makes the copy (`git init` + initial commit) and
drives the phases is Stage 2, step 4 — **not yet built**. This directory is the fixture input.

## What it is

An in-memory task store with a minimal API:

- `add(title)` — add a task, returns its id.
- `complete(task_id)` — mark a task done.
- `list(include_done=False)` — list tasks (open by default).

## Layout

- `taskstore.py` — the library.
- `test_taskstore.py` — its test suite (run with `pytest`).

This is fixture data: it is excluded from the plugin's own lint/test runs.
