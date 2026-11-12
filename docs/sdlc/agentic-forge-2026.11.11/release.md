---
type: release
feature: agentic-forge-2026.11.11
status: final
version: 2026.11.11
date: 2026-11-12
changelog:
  - "The routing note sizes the process; its off switch is documented (ADR 0110)."
  - "A session's own gh pr merge meets the PR watcher's gate; unattributable commands fail open with a notice."
  - "code-review checks the consumers of any tightened contract; af.py pr-review builds a pinned, mention-safe GitHub review."
  - "Phases write where the repository keeps its features (af.py artifact-home); product amends a PRD in its own format."
  - "Patterns for fleet coordination and for recall by the spawning session."
  - "A terraform-patterns pack; review-decision refuses an unknown verdict."
breaking:
  - "A session's gh pr merge on a draft, a PR with pending or failing checks, or unresolved review threads is refused."
  - "af.py review-decision --verdict accepts only approve or changes; anything else exits 2."
  - "The architect role may write tech-design.md and ADR records into an existing feature folder outside docs/."
---
# Release 2026.11.11

This release finishes the queue the f4ai fleet built: board `known-issues` items 7 to 15. Each item was verified
against the code before work started. ADR 0110 records the decisions.

## What changed

- **The routing note sizes the process.**
  - It no longer says "*especially* when doing it directly looks straightforward". It says the skill scales its
    process to the size of the change.
  - How to switch it off is documented: `{"routing_note":{"enabled":false}}` in `.agentic-forge/config.json`, or
    `AGENTIC_FORGE_ROUTING_NOTE=0`.
- **A session's own `gh pr merge` meets the PR watcher's gate.**
  - **What blocks:** a draft, checks not green, or unresolved review threads.
  - **What merges with a notice:** a PR with no checks at all.
  - **An accident guard, not a security boundary.** When it cannot tell which PR merges, or in what state, it lets
    the merge through with a notice saying why. That covers a state-changing command before the merge, a wrapper, a
    subshell, a variable, or an API failure.
  - **Hosts.** It contacts only github.com or the host of the session's own `origin`, and runs `gh` and `git` by
    absolute path.
- **Code review:**
  - The concurrent-change step fires on any tightened contract, and the session searches the base and open PRs for its
    consumers.
  - `af.py pr-review` builds a GitHub review and prints the post command; it never posts itself.
    - It is pinned to the head that was reviewed, with inline comments only inside the diff.
    - Every possible mention is neutralised.
    - The payload is written only as a `.json` file outside hidden directories.
- **Phases write where the repository keeps its features.** `af.py artifact-home` finds the feature folder and the
  ADR series. Folder names must be plain, and it prints shell-quoted commands.
  - Six phases write their documents and review rounds there.
  - architecture continues the repository's ADR numbering.
  - product can amend an existing PRD in its own format, always in the worktree.
  - The architect may write `tech-design.md` and ADR records into an existing feature folder. Every earlier refusal
    stays.
- **Patterns.**
  - `fleet-coordination.md` covers a fleet of running sessions over a hub: roster, unit envelope, decisions, idle
    peers, one escalation queue.
  - Knowledge recall is run by the spawning session, with the repository's own search or `vault-recall`. It passes
    the hits to the roles.
- **`terraform-patterns`** is an off-listing pack.
  - The agent runs only offline checks; plan and apply against a real backend are the human's.
  - The profile lints with `tflint` when it is configured, and the commit gate never runs it.
- **`review-decision --verdict`** refuses an unknown verdict (`approved` exits 2).

## Upgrade notes

- Restart sessions onto 2026.11.11.
- A session that merges with `gh pr merge` may now be refused with reasons. To wait for checks, run
  `gh pr checks <n> --watch` in one call and merge in the next.
- Scripts that pass `--verdict approved` must pass `approve`.

## Measured

- **Tier-1b, live, on the new routing note:** pooled activation 0.863 (69/80), passing the 0.80 gate.
  - The last recorded baseline is 0.940; it was measured with `skill-factory` in the stand.
  - develop was 2/5 and deep-review 3/5. Every other skill was ≥ 0.75.
  - The difference is about two standard errors at n = 80. The cause is not established; an `--ask-why` run on
    develop is the next diagnostic.
- **Review loop:** three rounds plus a user-approved confirming check.
  - Lenses: four reviewers, a security engineer, and the external codex lens.
  - Round-1 majors fixed include:
    - repository folder names reaching shell commands;
    - `npm`-style install risks;
    - the gate being switched off by `2>&1`;
    - amend editing the main checkout;
    - a symlinked output directory in pr-review.
  - Round 3 found that an uppercase URL scheme bypassed the merge gate's host check. It is fixed, together with the
    security engineer's last minors.
- **QA:** end-to-end tests run every field repro through the shipped entry points as processes. No defects were
  found.
- **Tier-0:**
  - `dev/validate.py` is clean; the listing stays at 6910/6910.
  - pytest: about 5,640 tests, coverage 96%.
  - ruff and mypy are clean.
  - `dev/hook_smoke.py` passes on Python 3.9.25.

## Not validated

- Tier-2 for the architect role and the edited skills, and Tier-3 with feature-folder detection. They need live
  sessions; run them on demand.
- How GitHub renders the neutralised mentions.
- The merge gate against a real GitHub Enterprise origin (covered by stubs only).

## Next

The queue is empty except item 6, subagent cost. It needs Tier-2 runs at Sonnet and is waiting for a decision.
