# 0067 — Deep-review remediation: connect the safety machinery, and stop the harness lying

Status: Accepted — **implemented**. Corrects [0063](0063-autonomous-pr-watch.md) (autonomous PR
watch), [0064](0064-tier1-measurement-integrity.md) (Tier-1 parser), [0065](0065-merge-outcome-is-observed.md)
(merge confirmation) and the escalate contract shared by
[0060](0060-skeptic-loop-architecture-plan.md) / [0061](0061-skeptic-loop-research-ux.md) /
[0062](0062-skeptic-loop-marketing.md).

## Context

A six-lens adversarial review of releases 2026.7.5 / 7.6, with every finding verified against source.
The releases had passed **the whole pyramid**: Tier-0, live Tier-1 (6/6 at 1.000), live Tier-2 (2/2),
and live Tier-3 (three scenarios). The review still found two blockers and a dozen majors — because
the pyramid checks *behaviour*, and these were defects of **wiring, contract and truthfulness**.

Three independent lenses converged on the same first finding, which is the strongest signal the
method produces.

## Decision

### 1. The merge machinery is connected — and the library, not the caller, decides

`merge_readiness`, the no-merge-after-push rail and `confirm_merged` had **zero production callers**:
`dev/pr_watch.py` passed no merge seam, and `pr_watcher_auto_merge` was resolved into `Settings` and
read by nothing. The only path that could merge was the skill instructing a model to run
`gh pr merge` over Bash, where all three rails were prose. ADR 0063 §4's claim — *"enforced in the
tested core, not left to the caller"* — was false in effect.

- `run_watch` now **recomputes** `merge_readiness` from the state it was given. A caller can no
  longer assert readiness (the old `merge_decision=` parameter is gone), so a stale or forged
  decision cannot merge.
- Merging requires a second, independent key: `auto_merge=True`, mirroring the setting.
- `dev/pr_watch.py` wires `merge=` / `confirm_merged=` **always**; `auto_merge` is the switch. The
  tested rails are therefore on the executing path whether or not merging is enabled.

### 2. The merge gate sees what it was blind to

- **`CHANGES_REQUESTED`** blocks. A "request changes" review with only a summary body creates **no
  review thread**, so the thread-count clause alone let the gate open over an explicit objection.
  Latest review *per author*, so approve-after-changes clears.
- **A truncated thread list** blocks: `reviewThreads(first:100)` had no `pageInfo`, so a PR with more
  threads presented as having fewer — and a *missing* thread read as an *absent* one. This is the
  same rule `checks: NONE` already follows: absence of data is not evidence of green.
- **A `CLOSED`/`MERGED` PR** blocks, and `PR_QUERY` now fetches `state` — the autonomous loop
  previously had no terminal signal at all.

### 3. The watcher's kill switch left its own blast radius

`<repo>/.agentic-forge/config.json` is a **committed, tracked file**, and the scheduled driver
resolved settings *after* `gh pr checkout`. A pull request could therefore ship a config that
rewrote `pr_watcher.bot` — making its author's review threads invisible to the gate — or set
`auto_merge`, and the watcher would read its own guardrails from the branch under review.
`run_scheduled` now resolves settings **before** checkout and passes the trusted values down as argv.
`auto_merge` additionally demands a real boolean (`is True`), not the widened truthy set that a
config slipping past an absent `jsonschema` could carry.

### 4. `escalate` now actually stops the handoff

Each writer phase writes its artifact **before** the loop, `status` was inert (`handoff.py` says so
explicitly), and no consumer checked it. So an escalated run left a schema-valid artifact that the
next phase happily consumed — and **Tier-3 scored such a run green**, because its checkpoints assert
"exists and validates", which is exactly `gate_green`.

`handoff.is_handoff_ready` is the shared rule (an unknown or missing status reads as *not* ready);
the seven writers set `status: in-review` on escalate; the four consumers refuse to build on an
unready upstream artifact; and `_artifact_checkpoint` now asserts readiness, so the E2E can tell the
two outcomes apart.

### 5. The Tier-1 parser missed its own founding case

ADR 0064 was written because a **Russian** prose reply was scored as a routing decision. Its fix
counts `[a-z0-9-]+` runs — which finds almost nothing in Cyrillic, so that very reply still passed
the cap and was scored as a vote for the one English word it contained. Now:

- a **non-Latin letter-run guard** (the skill names and answer format are English);
- **negation and acting markers** reject "…mentions research, but none of the skills fit" and "I will
  now analyse the repository and prepare a research summary" — both previously scored as votes;
- an explicit **decline vocabulary** ("No skill fits", "n/a") counts as the `none` *decision*, since
  declining is the correct answer on should-not-trigger prompts and treating it as silence drained
  specificity samples exactly where the router is right;
- **ambiguity is rejected** rather than resolved by "first-mentioned wins", which was a guess dressed
  as a decision;
- a **minimum-valid-samples floor**: a rate from one surviving call was averaged with the same weight
  as one from five. Below half the samples the prompt is unmeasured — the loud path that already
  exists.

The cap rose from 12 to 16 because natural terse answers run to 13 tokens and rejecting them
hard-failed a router that had answered correctly five times out of five. Precision no longer rests on
the count.

### 6. The hook missed the shape it was built for

`_segments` split on whitespace-delimited operators only, so **newlines were not separators** — and
`git push …\ngh pr create …`, the flagship path of ADR 0063, never fired. Unspaced `;`/`&&`, env
prefixes (`GH_TOKEN=x gh pr create`) and wrappers likewise. And a **failed** create — `gh` prints
`already exists:` plus *that* PR's URL on stderr — announced success, which in autonomous mode starts
a watch over a PR the session did not create. The hook now reads the **stdout** channel only.

### 7. Observability restored, and the shape made a gate

None of the seven loops persisted a `review.md`, so ADR 0040's non-convergence scan — whose stated
premise is *"the loop already records its state"* — could not fire for a single one of them. Each
loop now persists `review-<artifact>.md` per round, and `REVIEW_GLOB` matches it.

`tests/test_review_loop_shape.py` pins the contract that had shipped broken twice: every one of the
seven has `Bash` + `Task`, invokes `review_loop_decision`, and passes **its own** `KINDS` key. A
wrong kind would silently fall back to the *code* criteria with every gate still green.

## Alternatives considered

- **Keep the merge in the skill and correct the docs instead:** rejected — a rail that only exists as
  prose is not a rail, and the library's version was already written and tested. Connecting it costs
  less than maintaining an honest description of an unenforced one.
- **Have `run_watch` trust a caller-supplied `MergeDecision`:** rejected (it was the status quo) —
  the caller is the thing most likely to be wrong, and the state is right there.
- **Make `escalate` delete the artifact:** rejected — destroying a draft loses the work the loop just
  did. Marking it not-ready keeps it inspectable while making it unusable downstream.
- **Raise the Tier-1 cap and stop there:** rejected — it would readmit the English "I will now
  analyse…" case. The script/negation/acting guards are what carry precision.
- **Auto-repair frontmatter, or lower thresholds:** rejected on the same principle both times — the
  fix belongs where the defect is, not in the measuring instrument.

## Consequences

- The autonomous watcher's safety properties are now enforced by code on the path that executes, and
  a PR can no longer rewrite the guardrails applied to it.
- An escalated phase can no longer hand off, and Tier-3 can no longer score one green.
- Tier-1 numbers recorded **before** this change were measured with the parser corrected by 0064 but
  still blind to non-Latin prose, negation and thin samples; they remain "≥ this, possibly higher".
- `review.passes` is documented for what it actually does (it calibrates the scan, not the loops).
  Making the loops read it is deferred: they are model-followed prose, and threading a setting
  through them would add a second source of truth for the cap.
- The deep review that produced this is itself the argument for running one: every finding here
  survived a pyramid that was entirely green.
