---
type: review
feature: agentic-forge-2026.11.21
target: master..release/2026.11.21
iteration: 1
verdict: approve
findings: []
---

# Review: item 6 rest and the closable follow-ups

The release branch combines five reviewed branches on master 39898fb (v2026.11.20). Decision: proceed (verdict
approve, gate green).

## Harder Tier-2 cases and the run that moved no role (feat/tier2-hard-cases)

- **Round 1.**
  - Reviewer: changes. The major: architect case 4 could be met by an escrow design. Fixed: the PRD now caps a
    balance read at p99 and requires fresh reads, and the assertion is broadened. Minors and nits applied.
- **Codex.** Approve, no findings.
- **The tier promotion.**
  - First recorded, then reverted after review. The reviewer pointed out that the cases did not separate the tiers
    for the three roles, and that the qa-engineer promotion's premise would be lost.
  - The amendment now records the run and keeps all four roles at `default`. Reviewer round 2 approved, with three
    wording nits, all applied.

## reader role (feat/reader-clerk-roles)

- **Round 1** (reader and clerk): reviewer, security engineer and codex all returned changes.
  - The clerk was deferred.
  - The reader got a secrets rule and a fake-token assertion.
  - The `git` workspace mode was removed.
  - The api runner refuses workspace cases.
- **Round 2.** Reviewer approved, with minors. Codex: changes. Fixture containment was not on the live path, and a
  malformed contract aborted the preflight. Both fixed.
- **Round 3.** Codex: approve, no findings.
- **Tier-2 reader.** 1.000 at Opus 5.5.

## omitClaudeMd harness (feat/harness-omitclaudemd)

- **Rounds 1 to 3.** These turned a token-total validity check into a per-arm probe. They also added input
  fingerprints, atomic arm records, and usage kept independent of grading.
- **Round 4** (owner-approved). Two codex majors were fixed: an INVALID arm can never be recorded as a baseline, and
  the probe keeps its whole answer. Codex: approve, no findings.
- **The live A/B.**
  - Both pairs were VALID.
  - The reviewer's `on` arm read the file, so the reviewer is undecided.
  - security-engineer passes and omits CLAUDE.md.

## Windows lookups (fix/win-lookups)

- **Codex.** Approve, no findings.
- **Security engineer: changes, with one major that predates this change.** The PR watcher's fixer started `claude` by
  a bare name from a PR's worktree; on Windows that name could resolve to a `claude.exe` committed on the branch.
  Fixed: the fixer passes the absolute path `trusted_program("claude")` finds.
- **Its two nits were also fixed.** With `PATH` unset, the lookup falls back to the gate's fixed default. On a Windows
  host, a `PATH` entry needs a drive or UNC prefix.
- **Codex on that delta.** Approve, no findings.
