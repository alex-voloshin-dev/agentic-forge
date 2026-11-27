---
type: release
feature: agentic-forge-2026.11.19
status: final
version: 2026.11.19
date: 2026-11-27
changelog:
  - "The merge gates (merge_preflight hook, PR watcher) and af.py pr-state follow review-thread pages up to 10 pages (1,000 threads) instead of holding every PR past 100 threads as truncated; fail-closed past the cap or on any page not read (ADR 0110, second amendment)."
  - "The commit gate's narrowing runs git by an absolute path from the absolute PATH entries (Windows .exe/.com only), like the gate's own program; no such git leaves the whole gate running (ADR 0115, amendment)."
breaking: []
---
# Release 2026.11.19

Two follow-ups recorded as known limits in 2026.11.15 and 2026.11.17.

## What changed

- **Merge gates read review threads past the first 100.**
  - **The problem.** Both merge gates and `af.py pr-state` read `reviewThreads(first:100)`. That count includes resolved
    threads, so a PR that had ever had more than 100 threads stayed held as "truncated" for good. Since 2026.11.17
    every own-PR `changes` finding opens a thread, so a long review loop could hit this.
  - **Now.** They follow the pages, 100 threads each, up to 10 pages (`THREAD_PAGES`, 1,000 threads), inside each
    caller's existing time budget: the hook's 12 s, the watcher's 120 s, `pr-state`'s 60 s.
  - **Still fail-closed.** The list counts as truncated and the PR is held past the cap, and also when a later page:
    - fails, or runs out of time;
    - is about another PR;
    - has no usable cursor;
    - or does not say whether more pages follow.

    A failed first read in the hook still fails open with a notice, as before.
  - **In the hook, the 12 s deadline usually sets the practical limit.** A very large PR whose threads are all
    resolved can still be held there while the watcher merges it.
- **The commit gate's narrowing runs git by absolute path.** `gate_scope` ran `git` by its bare name, which on Windows
  can resolve from the repository. It now resolves git the way the gate resolves its own program: absolute `PATH`
  entries only, and on Windows only `.exe`/`.com`. The lookup is done once per hook run. If no such git is found, the
  narrowing does not run, so the whole gate runs.

## How it was checked

- **Review.**
  - The reviewer, the security engineer and the external lens (codex) all approved.
  - Codex and the reviewer both found the same minor issue: a page without a boolean `hasNextPage` could end the list.
    It was fixed with regression cases.
  - The security engineer's nit (a test that pins the cursor as a `-f` value, including a cursor that starts with `-`)
    and the reviewer's doc nits were applied.
  - Details are in `review-code-1.md`.
- **Tier-0:** `dev/validate.py`, `ruff`, `mypy`, the full pytest suite, and `dev/hook_smoke.py` under Python 3.9.

## Not validated

- **Tier-1, Tier-1b, Tier-2 and Tier-3:** not run. No skill or role changed.
- **The live GitHub API.** Paging was not checked against it; the tests use a `gh` stub that answers pages by cursor.
- **Windows.** The behaviour is tested by simulation, not on a Windows host.

## Known limits

- These sites use `shutil.which` with a relative-path refusal, so on Windows they could still pick a `git.cmd` from an
  absolute `PATH` entry (follow-up, recorded in the ADR 0115 amendment):
  - `guardrails.commit_dir`
  - `guardrails._bin_dir_doubt`
  - `role_scope._git_version`
  - `merge_preflight._git_path`
- `af.py pr-state` and the PR watcher's `_fetch` run `gh` by its bare name from the repository directory. They are CLIs,
  not hooks; this is the same follow-up.
