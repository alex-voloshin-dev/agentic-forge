---
type: release
feature: agentic-forge-2026.7.6
status: final
version: 2026.7.6
date: 2026-07-26
changelog:
  - "Added: autonomous PR watch (ADR 0063) — the watcher carries a PR to done: monitoring starts at PR creation via a PostToolUse hook, re-checks every `poll_seconds` (default 600), triages each review comment (valid -> fix through the software-engineer under the bounded review loop; invalid -> reasoned refutation, thread left open), resolves conflicts, and merges once a pure `merge_readiness` gate opens (not draft, checks green, no unresolved actionable threads, MERGEABLE)"
  - "Added: `pr_watcher.{auto_merge, merge_method, poll_seconds}` settings — auto_merge OFF by default; merge_method clamped to {rebase,squash,merge} in the library, not just the schema, because it reaches argv as `--<method>`"
  - "Changed: ADR 0044/0045's `never merges` invariant is deliberately reversed and annotated in both ADRs; `never force-pushes` remains absolute and is now the only such invariant"
  - "Fixed: Tier-1 scored broken router calls as routing decisions (ADR 0064) — an off-format reply is now INVALID, excluded from the denominator and reported; a prompt whose every call was invalid is `unmeasured` and fails rather than reporting a fabricated 0.0; the router gets `--system-prompt` (replace) instead of append"
  - "Fixed: the merge outcome is observed, not inferred from the command (ADR 0065) — `gh pr merge` merges remotely then does local work that can fail on its own, so `merged_argv`/`parse_merged` + a `confirm_merged` seam read the PR's state; without the seam a failure still propagates"
  - "Fixed: every artifact-writing skill now demands valid YAML frontmatter (ADR 0066) — an unquoted colon in a frontmatter list entry invalidates the whole artifact; the guidance existed only in `ux-design` and one E2E prompt, so five skills lacked it"
breaking: []
---

# Release 2026.7.6

The watcher carries a PR to done — and the eval harness stops lying about it. Two capabilities and
two integrity fixes.

The through-line: **three of the four were found by *running* the thing, not by reading it.** The
Tier-1 corruption surfaced only when raw router replies were captured; the frontmatter defect only
when Tier-3 was finally run live; the merge-atomicity bug only when a real `gh pr merge` failed
halfway during this very release cycle. Tier-0, Tier-1, Tier-2 and the Tier-3 *dry* run were green
throughout.

## What shipped

**Autonomous PR watch (ADR 0063).** Monitoring starts at PR creation (a `PostToolUse` hook that
matches `gh pr create` at a command position and requires the printed URL); each pass triages review
comments — a valid one becomes a fix routed through the `software-engineer` under the bounded review
loop, an invalid one gets a reasoned refutation and its thread is left **open** — resolves
conflicts, and merges once the gate opens. Two readings of the spec are recorded deliberately:
"no comments" means no unresolved *actionable* threads (else any reviewed PR is permanently
unmergeable), and "green builds" requires builds to *exist* (a `NONE` check rollup blocks). The
external reviewer's window is the **poll interval**, not a configured timeout — a fresh PR has
`PENDING` checks, so the earliest merge is one `poll_seconds` after opening.

**`never merges` reversed, deliberately (ADR 0063).** Rails: `auto_merge` off by default,
`merge_method` clamped in the library (it reaches argv as a flag), no `--admin`, never merge in the
pass that pushed a fix. `never force-pushes` stands and is now the only absolute; both 0044 and 0045
are annotated so neither reads as still-true.

**Tier-1 measurement integrity (ADR 0064).** `product` scored recall 0.800 → 1.000 → 0.720 in one
hour against a byte-identical listing. Not throttling — 50 captured calls had **zero** empty
replies. The parser was mining off-format prose for the first skill-like word and scoring it as a
routing decision. The corruption was asymmetric (recall falls, specificity stays a perfect 1.000),
so it read like a clean result; the next step would have been editing a description and spending the
router's ~1% listing budget on a defect that was never there.

**The merge outcome is observed (ADR 0065).** `gh pr merge` exited non-zero with
`fatal: 'master' is already used by worktree` while `gh pr view` reported `state=MERGED`. For an
autonomous loop, trusting the exit status means retrying an already-merged PR forever.

**Frontmatter quoting (ADR 0066).** An unquoted colon in a frontmatter list entry invalidates the
whole artifact. The guidance lived in `ux-design` and in one E2E scenario's prompt — patched twice
locally, never generalised. Fixed in the **skills**, not the E2E prompt: patching the fixture would
have turned the test green while every real user still produced an unparseable artifact.

## Verification

- **Tier-0**: `dev/validate.py` clean; `pytest` green; `ruff` / `mypy` clean.
- **Tier-1** (live, runs = 5): all six touched skills **1.000 / 1.000**, with ~20 of ~300 calls
  (6.7%) discarded — now visible on the summary line rather than silently scored.
- **Tier-2** (live, n = 5): `ux-design` 1.000 (σ 0.000), `marketing` 0.954 (lower bound 0.937).
  Closes the live re-run ADR 0037 §5 deferred.
- **Tier-3 (live, `--runner claude`)**: `product-inception` PASS, `market-brief` PASS; `spine`
  FAILED on `architecture` + `plan`, which is what surfaced ADR 0066, and **PASSES** on the re-run
  after the fix. `quality-gate` and `ops-incident` drive no changed skill and were skipped
  deliberately.

Not claimed: the autonomous watch has **not** been validated against a real PR end to end — the
capability ships tested at unit level with its live validation still outstanding, as ADR 0045's
runbook item already noted for the watcher core.

## Tag

`v2026.7.6` (annotated) on the merged master commit, created after the PR's rebase merge, per
CONTRIBUTING's "Cutting a release". Unlike 2026.7.5, this artifact ships **inside** the release
commit rather than trailing it.
