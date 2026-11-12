---
type: release
feature: agentic-forge-2026.11.10
status: final
version: 2026.11.10
date: 2026-11-11
changelog:
  - "The external review lens no longer drops out silently: prompt on stdin, any cwd, --repo on every call, a failure exits 3 (ADR 0109)."
  - "The knowledge vault is read from every folder, bounded, with MOC/INDEX/Home/README as the root map."
  - "Readiness reads review_decision (first written revise), not the repository's status; status is a legacy fallback."
  - "Stack profiles read the declared package manager and scripts, scan a monorepo root, use -race/golangci and verify/check, add Terraform, and say they are fallbacks."
breaking:
  - "external_review.py: exit 1 now means only a changes verdict; a failed call, timeout, refused argument or crash exits 3."
  - "Readiness: a plugin older than 2026.11.10 reads an artifact with review_decision escalate and status approved as ready; upgrade a fleet together."
  - "The commit gate no longer runs on a JS package without a lint script (it used to run npm run lint and fail open)."
  - "Vault note names index and home are reserved."
---
# Release 2026.11.10

This release fixes four bugs that the f4ai fleet reported from real repositories: board `known-issues` items 2 to 5,
across twelve threads. Each fix was verified against the code before work started and reproduced end to end after it.
ADR 0109 records the decisions.

## What changed

- **The external review lens no longer drops out silently.**
  - **Before:** develop writes the diff outside the repository. `external_review.py` passed the diff to codex as one
    argument, so a diff over 128 KiB failed, and codex refused to run outside a git repository. Both came back as
    "skipped", so the round lost its independent lens without anyone noticing.
  - **Now:**
    - The prompt goes on stdin, with `--skip-git-repo-check`.
    - Every documented call passes `--repo`, so a repository's `external_reviewer.enabled: false` is honoured from any
      cwd. Without `--repo` the CLI reads the git work-tree root, and refuses outside a work tree.
    - A failure is its own outcome (exit 3), recorded in the round and reported to the user.
  - **Measured on codex 0.167.0:** from a non-git directory, codex loads neither a `.codex/config.toml` nor
    `AGENTS.md`.
- **The knowledge vault is read from every folder.**
  - **Before:** a vault of 382 notes in `decisions/`, `learnings/` and so on loaded as one note.
  - **Now:**
    - Notes are found by name wherever they sit. The walk skips dot-folders, `_`-folders, README files and symlinks.
    - It is bounded: 5,000 notes, depth 8, 20,000 entries, and 32 MiB charged per file before it is read.
      Frontmatter is parsed only if it closes within 64 KiB.
    - Duplicate names are reported.
    - The root map can be `MOC`, `INDEX`, `Home` or, alone, `README`. A first capture in a README-mapped vault seeds
      the new MOC with README's links, so nothing becomes an orphan.
  - **Measured:** 2,000 notes load in about 1.2 s.
- **Readiness has a field of its own.**
  - A phase writes `review_decision: revise` with its artifact. The review loop's exit sets `proceed` or `escalate`,
    and only `proceed` is ready.
  - Without the field, the old `status` rule applies.
  - A repository's own lifecycle (`status: in-progress`, `draft`) no longer blocks develop.
  - `handoff-load` reports `ready_from`.
- **Stack profiles read what the repository declares.**
  - **JS/TS:** the declared package manager. A command is listed only when the script or tool exists, and npm runs
    as `npm exec --no` (no registry download).
  - **Monorepos:** a root with no manifest is scanned one level down, with a `dir` per service.
  - **Go:** `-race`, and golangci-lint when configured.
  - **JVM:** `verify` / `check` through the wrapper.
  - **Terraform:** a new profile.
  - **go-patterns:** a goroutine a test starts must stop before the test ends.
  - **Labelled as fallbacks:** develop prefers the repository's declared gate, but runs only the test, lint,
    typecheck and build steps of CI files.
  - **The commit gate still only narrows:** `npm run lint`, and only when a `lint` script exists.

## Upgrade notes

- Restart sessions onto 2026.11.10.
- Scripts that call `external_review.py`: exit 1 now means only `changes`. Every failure exits 3.
- Upgrade a fleet together. An older plugin reads an artifact with `review_decision: escalate` and `status: approved`
  as ready.
- `index` and `home` can no longer be note names in the vault.

## Measured

- **Review loop:** three rounds.
  - **Lenses:** four reviewers, a security engineer, and the external codex lens.
  - **Round 1:** codex reviewed a 268 KB diff from outside the repository, which is the bug-2 fix working live.
  - **Round 3:** every lens approved.
  - The final round is `review-code-3.md` in this folder.
- **QA:** 21 end-to-end tests run the field repros through the shipped entry points as processes. 17 of them fail on
  2026.11.9. No defects were found.
- **Tier-0:**
  - `dev/validate.py` is clean; the listing stays at 6910/6910.
  - pytest: about 4,870 tests, coverage 96.07%.
  - ruff and mypy are clean.
  - `dev/hook_smoke.py` passes on Python 3.9.25.

## Not validated

- Tier-1 and Tier-1b were not run, because no skill description changed.
- Tier-2 for the edited skills, and the Tier-3 spine with the new prompts and the `in-progress` plan fixture, were
  not run. They need live sessions; run them on demand before relying on the spine.
- The codex behaviour was measured on 0.167.0 only.
- `npm exec --no` was measured on npm 12.2.2.
- macOS and Windows were not covered beyond the unit tests.

## Next

The board queue, from item 6: subagent cost, the routing note, merge_preflight, code-review contract-tightening,
repository conventions and PRD amend, `af.py pr-review`, the fleet-coordination pattern, knowledge-recall project
search, a terraform-patterns pack, and review-decision verdict choices.
