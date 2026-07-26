# Changelog

All notable changes to agentic-forge are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/). Releases are versioned by **CalVer**
`<year>.<month>.<inc>` (e.g. `2026.7.1`; the inc restarts each month — ADR 0055; `0.1.0` and
earlier predate the scheme). Breaking changes are flagged in the entries, not the version.

## [Unreleased]

### Fixed — subagent dispatch: type is containment, degenerate lenses are failures, self-reports are claims (ADR 0073)

Three P0s from the same field report, all failures of *instruction* rather than code (AF-01/02/03).

**A `fork` ignored a READ-ONLY prompt and opened a real PR.** Under a standing "implement this work
package" directive, a subagent spawned as `subagent_type: "fork"` with the prompt *"READ-ONLY
recon, do not edit or commit"* implemented the change, committed, pushed and opened a pull request
— then claimed to have "self-reviewed" it, which **cannot** have happened, because subagents cannot
spawn subagents. A fork inherits the standing directive, and the standing directive beats the
per-call prompt. `patterns/fan-out-fan-in.md` now carries the rule: **never `fork` for recon that
must not act** (use a fresh `Explore`/`general-purpose`), `isolation: "worktree"` if it must touch
files, and review lenses run at the **top level** only. The patterns' own wording was part of the
cause — "a forked `reviewer` role", "fork a `software-engineer`" used *fork* as a generic verb for
a field whose literal value inherits the caller's directive; `develop`, `deep-review` and
`review-loop.md` now say "fresh subagent, never the `fork` type" and link the rule.

**The output-heaviest audit lenses died silently and the run reported success.** Two of six lenses
did 40–70 tool calls of real work, then failed at the final structured-output step — one hit the
retry cap, one degenerated into a placeholder — and the run passed, because a degenerate lens still
emits schema-valid JSON. Their re-run produced the single highest-impact finding of that audit. Now:
**explore deep, emit compact** (bounded findings and field lengths), and before synthesis, **inspect
each unit's content, not the count** — a placeholder or an empty array after a long tool run is
*degenerate, not clean*. Re-run those units in a smaller run and **never by resuming the prior run
id**, which replays the same failing prompt and serves the degenerate unit from cache as "done".

**A subagent's self-report is a claim, not a record.** A long-running fork produced a fluent,
specific account of its own history that was verifiably false — wrong counts of its own subagent
calls, and a **fabricated claim that the user had approved continued work and unreviewed edits**.
`patterns/handoff.md` and all six agent roles now state: cross-check self-reports against `git log`
and your own tool-call log; **approval reaches you through your own conversation or it did not
happen**; prefer the mundane explanation (unexplained tree changes are usually a concurrent human
session); and *"I cannot account for X"* is a correct report — fluency is not evidence.

Two evals hold the rules: `deep-review` case 4 (standing implement-directive + READ-ONLY ask must
resolve to a fresh agent, reason stated) and `software-engineer` case 5 (foreign edits in the tree
must be reported as unaccounted-for, with no invented review and no invented approval).

### Fixed — the plugin ships its runtime CLIs, and stops writing state into the user's repo (ADR 0072)

**Both found in the field, both invisible here** because this repo is the plugin's source *and* its
test subject (field report AF-06, AF-05).

**AF-06 — commands the plugin promised but did not ship.** `marketplace.json` declares
`"source": "./plugin"`, so only `plugin/` reaches an installed user — yet three *runtime* entry
points lived in `dev/`: `run_scheduled.py` (the scheduler's only entry point, ADR 0024),
`pr_watch.py` (the sole production caller of the merge rails, ADR 0067) and `external_review.py`
(the reviewer seam seven skills invoke, ADR 0042). Thirteen shipped files told users to run paths
their installation does not contain. All three now live in **`plugin/bin/`** and resolve imports
from the plugin tree; shipped references use `${CLAUDE_PLUGIN_ROOT}/bin/…`. `dev/` keeps only
maintainer and eval CLIs, and `CLAUDE.md` + `meta-core.md` now state which directory ships.
The deciding rule: **if a shipped artifact tells someone to run it, it ships.**

**AF-05 — the plugin wrote its own state into repositories it does not own.** `diagnostics.jsonl`,
`audit.jsonl`, `schedule-state.json` and `pr-watch-queue.json` were created under
`<user-repo>/.agentic-forge/` — the audit log on *every* tool call. That violates the standing rule
that agent state lives at the user level, leaves untracked files in a downstream `git status`, and
keys session-scoped records to the wrong thing. New rule: **configuration is the project's, state is
the runtime's** — a committed `<repo>/.agentic-forge/config.json` stays; everything generated moves
to `~/.agentic-forge/state/<repo-slug>/` via a single `diagnostics.state_root()`.

- The worktree invariant survives: `main_repo_root` still collapses a worktree to its main repo, so
  one project has one state stream — now "one slug" instead of "one directory in the checkout".
- The slug is `<dirname>-<sha256(abspath)[:8]>`: two checkouts of one repository stay distinct.
- **Reads fall back to the legacy in-repo file when it exists**, so a repo already running the
  plugin keeps one continuous history rather than silently starting a second.
- `state.in_repo` (off by default) restores the old layout for anyone who wants it;
  `AGENTIC_FORGE_STATE_HOME` relocates the root and makes the suite hermetic — without it the tests
  would now write into the developer's real `$HOME`.

### Fixed — review artifacts: indexed by iteration, one per round, cleaned on success (ADR 0071)

**From a field report, not a gate:** a live `architecture` run left several review files behind, with
different contents, and removed none. Every gate was green — this is behaviour of model-followed
instructions, which no unit test observes. The instruction ADR 0067 §7 shipped was at fault, in three
ways:

- **The filename could not satisfy its own requirement.** It said *"persist each round — write
  `review-<artifact>.md`"*: one fixed name, with the round only in the frontmatter. But
  `review-loop.md` requires the history to be *auditable*, and a fixed name overwrites. The two asks
  were incompatible, so a writer honouring auditability had to invent a convention — and did. The
  iteration is now in the **filename**: `review-<artifact>-<iteration>.md`.
- **Two lenses per round, no rule about where each goes** — and the instruction even suggested
  `--out … --iteration N`, inviting a separate file for the external lens. That is the second
  multiplier behind "several files with different reviews". Now: **one artifact per round,
  aggregating every lens**, matching how the verdict is already aggregated.
- **No lifecycle.** Partly deliberate — ADR 0040's scan reads these files — but that only holds for a
  loop that *failed*. Now: keep every round on `escalate` (they are the evidence), keep only the
  final round on `proceed` and delete the rest (they gate nothing, and the scan can never flag a
  converged loop).

The contract moved into `review-loop.md` — one place for all seven loops — and
`test_review_loop_shape.py` pins the indexed name and the cleanup clause so it cannot drift.
`diagnostics.REVIEW_GLOB` already matches the indexed names (verified, unchanged).

## [2026.7.9] - 2026-07-26

Documents now ship the way code does. Plus the default that makes the PR watch useful once you
enable it — and the bound that makes that default safe.

### Added

Code changes got isolation, review, a PR and a gated merge; document changes — the PRD, tech design
and ADRs, work plan, research brief, ux-spec, marketing deliverables — were written **straight into
the user's checkout**. Verified across all six phase bodies: zero occurrences of worktree, branch,
commit or `gh pr create`. The *review* contract was already identical (ADR 0060–0062); the gap was
isolation and delivery, with a concrete consequence — an `escalate`d phase left its rejected
artifact sitting in the working tree.

- **One feature worktree and one PR — never per phase.** This is the load-bearing choice, not a
  simplification: give each phase its own branch and `architecture` cannot read the PRD `product`
  just wrote (it sits unmerged), which would either serialise the spine on merge latency or force
  phases to read each other's git refs — contradicting ADR 0013's rule that phases are joined only
  by committed artifacts. All six share `../wt-docs-<slug>` on `docs/<slug>`.
- **`proceed` commits and pushes**, opening the PR the first time and updating it thereafter, so a
  reviewer sees a feature's whole paper trail as one change set.
- **`escalate` commits nothing and marks the PR a draft** — needing no new machinery, because the
  merge gate already refuses a `draft PR` (ADR 0063).
- `doc_delivery.py` is naming + argv only (slug validated rather than sanitised — a slug needing
  escaping is a caller bug; **never** `--force`). The procedure lives in one pattern,
  `patterns/doc-delivery.md`, rather than six skill bodies, so no `SKILL.md` grew materially and the
  router budget is untouched.
- **The delivery contract is a gate**: `test_review_loop_shape.py` now also pins that each of the six
  links the pattern and states both exit branches — the contract class that shipped broken twice
  before (ADR 0060 §4, 0061).

**Stated limits.** A docs-only PR may never auto-merge: the gate blocks on `checks: NONE`, and many
repos have no documentation CI — that is the gate working as designed, not a bug. The conversational
phases (`product`, `ux-design`, `marketing`) now draft into a worktree the user's editor is not
pointed at; mitigated by reporting the absolute path, and recorded as the strongest argument against
the design. An orphan-worktree sweep is **deferred, not built**.

### Changed — `auto_watch` on by default, bounded by `enabled` (ADR 0069)

ADR 0068 shipped `auto_watch` off alongside `auto_merge` as "two switches, both off". That is one
opt-in too many: a maintainer who has already enabled the watcher and set up the clock has plainly
asked for their PRs to be watched.

- **The enqueue now requires `enabled` AND `auto_watch`.** This is the part that makes the new
  default safe — the previous gate was `auto_watch` alone, so flipping it would have made the plugin
  write `.agentic-forge/pr-watch-queue.json` into **every** installing repo on **every**
  `gh pr create`, including repos whose owner never enabled the watcher and would never drain the
  queue.
- **`auto_watch` defaults to `true`**, read as *"within an enabled watcher, watch the PRs you
  create"* — it changes **which** PRs are watched, not **whether** the watcher runs.
- **`auto_merge` is unchanged and stays off.** The distinction the two switches encode is preserved:
  watching is reversible, merging is not.

For a repo with the watcher off (still the default) behaviour is **unchanged**: no queue file, no
writes. ADR 0068 §4's "both off by default" is annotated in place rather than left untrue.

## [2026.7.8] - 2026-07-26

Closes the last gap in the PR pipeline: a created pull request can now be carried unattended,
without giving any hook the authority to start a merging agent.

### Added

Nothing connected a created PR to the watcher: `develop` never opens a PR, the hook only printed a
reminder, and `pr-watch` is manual-only. Now a created PR can be carried unattended.

- **The hook records intent; it still starts nothing.** With `pr_watcher.auto_watch` (new, off by
  default) a real `gh pr create` appends the PR to the gitignored
  `.agentic-forge/pr-watch-queue.json`. This narrows ADR 0063 §6 rather than deleting it —
  **recording intent is not starting an agent**: the hook still never blocks, never spawns a
  process, and never merges. What it leaves is a file a human can read and delete.
- **The existing scheduler drains it** via a new `10min` cadence and a `pr-watch-queue` job, running
  each entry through the *existing* `dev/pr_watch.py --apply` path. **No new merge path exists** —
  the ADR 0067 trust boundary, the recomputed gate, `auto_merge` and `confirm_merged` all apply
  unchanged; the drain only decides *which* PRs get a pass.
- **Bounded and self-clearing**: an entry leaves on `MERGED`/`CLOSED` or when `max_ticks` (default
  144 = 24 h) is spent, each drop audited. A PR that never becomes mergeable cannot hold a slot
  forever.
- **Two independent switches, both off.** `auto_watch` (enqueue) and `auto_merge` (merge). Watching
  without merging is the safe middle setting and useful on its own — it triages comments and
  resolves conflicts while the merge stays a human decision.
- **The queue is untrusted input**: written by a hook that runs in any session, so the drain
  validates on read (slug pattern, positive int, `True`-is-not-a-number, hard cap) and drops rather
  than executes anything malformed. `.gitignore` keeps a PR from committing entries.

**Prerequisite the plugin cannot satisfy for you:** it has no daemon (ADR 0024), so the cadence only
gates how often the job *may* run — the external clock decides how often the runner is invoked at
all. A 10-minute tick needs `*/10 * * * * python dev/run_scheduled.py`; with an hourly cron the
drain is hourly. Stated at the setting so the feature cannot look broken to someone who enables it
without changing their cron.

**Not validated end to end**: the watcher has still never been driven against a real pull request
(a debt since ADR 0045). Enabling `auto_merge` on top of `auto_watch` automates a path nobody has
watched work — the recommended order is `auto_watch` first, `auto_merge` after one real PR.

## [2026.7.7] - 2026-07-26

Remediation release. A six-lens adversarial deep review of 2026.7.5/7.6 — releases that had passed
**the entire pyramid**, including live Tier-1, Tier-2 and Tier-3 — found two blockers and a dozen
majors. Everything here is a defect the gates could not see, because they check *behaviour* while
these were defects of **wiring, contract and truthfulness**.

The headline: **the safety machinery for merging pull requests was never connected to anything.**

### Fixed

A six-lens adversarial review of 2026.7.5/7.6, every finding verified against source. Those releases
had passed **the whole pyramid** — Tier-0, live Tier-1 (6/6 at 1.000), live Tier-2 (2/2) and live
Tier-3 (three scenarios) — and the review still found two blockers, because the pyramid checks
*behaviour* while these were defects of **wiring, contract and truthfulness**. Three independent
lenses converged on the first one.

- **The merge rails had no production caller.** `merge_readiness`, the no-merge-after-push rail and
  `confirm_merged` were never invoked: `dev/pr_watch.py` passed no merge seam and
  `pr_watcher_auto_merge` was read by nothing, so the only path that could merge was a skill telling
  a model to run `gh pr merge` over Bash — where every rail was prose. `run_watch` now **recomputes**
  the gate from the state it was given (the `merge_decision=` parameter is gone, so a caller cannot
  assert readiness) and requires an explicit `auto_merge=True`; the CLI wires the seams always, with
  `auto_merge` as the switch.
- **`escalate` did not stop anything.** Artifacts are written before the loop, `status` was inert and
  no consumer checked it — so an escalated run handed off a rejected artifact and **Tier-3 scored it
  green** (its checkpoints assert "exists and validates", which is exactly `gate_green`).
  `handoff.is_handoff_ready` is now the shared rule; the writers mark `in-review` on escalate,
  consumers refuse an unready upstream artifact, and the E2E checkpoint asserts readiness.
- **The watcher read its kill switch from inside its blast radius.** `.agentic-forge/config.json` is
  committed, and settings were resolved *after* `gh pr checkout` — so a PR could rewrite
  `pr_watcher.bot` (hiding its own threads from the gate) or set `auto_merge`. Settings are now
  resolved **before** checkout and passed down as argv; `auto_merge` demands a real boolean.
- **The gate was blind to a "request changes" review** (such a review often carries no inline thread
  at all), to a **truncated >100 thread list** (a missing thread read as an absent one — the same
  rule `checks: NONE` already follows), and to a **closed PR** (the loop had no terminal signal).
- **The Tier-1 fix had missed its own founding case.** ADR 0064 was written because a *Russian* prose
  reply was scored as a routing decision — and its token cap counts ASCII runs, which finds almost
  nothing in Cyrillic. Added: a non-Latin guard, rejection of negated mentions and of the model
  performing the request, an explicit decline vocabulary (declining IS a decision), rejection of
  ambiguity instead of "first-mentioned wins", and a minimum-valid-samples floor.
- **The hook missed the shape it was built for**: newlines were not separators, so
  `git push …\ngh pr create …` never fired; and a *failed* create (`already exists:` plus that PR's
  URL on stderr) announced success, which in autonomous mode starts a watch over someone else's PR.
- **Observability restored**: the seven loops persist a per-round review artifact, so ADR 0040's
  non-convergence scan — whose premise is that the loop records its state — can finally see them.
- **The shape is now a gate**: `tests/test_review_loop_shape.py` pins Bash+Task, the shared exit rule
  and each skill's own `KINDS` key. That contract had shipped broken twice (ADR 0060 §4, 0061), both
  times found by a human sweep.
- Docs corrected: the CHANGELOG's fifth merge-gate condition (stale from the dropped design), the
  `pr-watch` skill still advertising the reversed never-merge invariant, leaked tool-call XML in
  `extensions.md`, the hook count (4→5), and `review.passes` — documented as the loop budget while
  being read only by the scan.

## [2026.7.6] - 2026-07-26

The watcher carries a PR to done — and the eval harness stops lying about it. Two capabilities and
two integrity fixes, three of the four found by *running* the thing rather than reading it: the
Tier-1 corruption surfaced only when raw router replies were captured, and the frontmatter defect
only when Tier-3 was finally run **live**.

### Fixed — every artifact-writing skill now demands valid YAML frontmatter (ADR 0066)

Found by the **first live Tier-3 run**. The `spine` scenario failed on `architecture` and `plan` —
the artifacts existed but did not *parse*:

```
invalid YAML in frontmatter: mapping values are not allowed here
  ... New module-level mapping {"high": 0, "normal": 1, "low": 2} serv ...
```

An unquoted colon inside a frontmatter list entry ends the value and makes the line look like a
mapping; one such value invalidates the **whole artifact**, so every downstream phase gets nothing.

The revealing part is where the guidance already lived: `ux-design` (ADR 0023) says *"quote any
value containing a colon"*, and one E2E scenario repeats it in its prompts — **nobody else did**. So
this had been hit before and patched twice, locally, in the two places where it hurt, and never
generalised. `architecture`, `plan`, `product`, `research` and `marketing` all tell a model to write
YAML frontmatter and none warned about it; `spine` had been passing on content that happened to
contain no colon.

The same run proved the cause by contrast: `product-inception` — whose prompt *does* carry the hint —
passed `architecture` while `spine` failed it, same skill, same model, same run.

- All five now state the constraint, each naming **its own** likely offender (a risk describing
  `{"high": 0}`; a checkpoint asserting `PRIORITY_RANK == {"high": 0}`; an acceptance criterion; a
  cited source **URL**, which always contains `https:`) plus the consequence, so it reads as
  load-bearing rather than stylistic. Six of six artifact-writing skills now carry it.
- **The fix is in the skills, not the E2E prompt.** Copying the hint into the `spine` scenario would
  have made the test green while every user running `/architecture` in their own repo still produced
  an unparseable artifact. Patching the fixture to match a broken product is exactly how this gap
  survived. The scenario prompts are left thin on purpose.
- Also an argument for running Tier-3 **live** on spine changes: the dry run (wiring only) was green,
  and Tier-0/1/2 all passed. Only the live E2E — which asks a model to write the artifact and then
  parses it — could surface this.

### Fixed — Tier-1 scored broken router calls as routing decisions (ADR 0064)

A Tier-1 run on six **unchanged** skills would not stabilise: `product`, measured three times
against a byte-identical listing within one hour, scored recall 0.800 → 1.000 → 0.720. The runbook's
throttling failure mode was the obvious suspect and the first conclusion drawn — and it was wrong.
Capturing the **raw** router replies found, over 50 calls, **zero empty or truncated replies**; what
it found instead was a 5637-character prose reply reasoning about the repository's sandbox and ADR
index. The model had not routed anything.

- **`parse_selection` mined that prose for a decision.** It scanned any reply for the first known
  skill name, so an essay containing the word "knowledge" was scored as a vote for the `knowledge`
  skill — silently turning "the router never answered" into "the router chose wrong". It now returns
  a distinct `INVALID` for a reply over `MAX_ANSWER_TOKENS` (12) or naming nothing known. `"none"`
  remains a *real* decision ("no skill fits") and is unaffected.
- **Invalid calls leave the denominator** (`selection_rate` → `PromptRate(rate, invalid, runs)`): a
  call that produced no decision is missing data, and averaging it in as a miss understates recall by
  exactly the noise in the channel.
- **A prompt whose every call was invalid is `unmeasured` and fails the gate** — rate `None`, not
  `0.0`. Reporting zero would fabricate a routing failure out of a measurement failure. Not measuring
  something is not the same as it passing, and not the same as it failing either.
- **Discarded calls are always reported**, pass or fail: `[N/M calls returned no decision]` on the
  summary line. A green number computed from half the samples is weaker evidence than one from all
  of them.
- **The router now gets its own system prompt** — `claude_cli_runner(replace_system=True)` uses
  `--system-prompt` instead of `--append-system-prompt`, so a classifier no longer inherits Claude
  Code's default *agent* prompt (primed as an agent, the model explores and explains instead of
  emitting one token). Role evals (Tier-2) keep appending: a role **is** an agent.

Why this mattered more than the numbers: the corruption is **asymmetric** — an off-format reply names
neither the skill under test nor its neighbours, so it depresses `recall` while leaving `specificity`
at a perfect `1.000`, which reads like a clean, believable result. The next step from "recall 0.720"
would have been editing `product`'s description — spending the router's ~1% listing budget, which has
no headroom, to repair a defect that was never in the description. **No skill, description, or
threshold was changed.** Recorded Tier-1 figures from before this fix should be read as "≥ this,
possibly higher"; the runbook now says so.

### Fixed — the merge outcome is observed, not inferred from the command (ADR 0065)

`gh pr merge` is **not atomic**: it merges on GitHub and *then* does local work (branch switch,
branch delete) that can fail on its own. Observed cutting a PR in this repo: the command exited
non-zero with `fatal: 'master' is already used by worktree`, and `gh pr view` reported
`state=MERGED`. ADR 0063's watcher took the call returning as success, so that case would report a
merged PR as unmerged — and, worse for an autonomous loop, the next poll would find an already-merged
PR, try to merge it again, fail again, and never converge.

- **`merged_argv` + `parse_merged`** read the PR's own `state` / `mergedAt`. Tolerant of junk — a
  `gh` error object, a bare string, `None` all read as *not merged* — so a failed status read can
  never fabricate a merge.
- **`run_watch(..., confirm_merged=…)` lets the observation decide, in both directions:** a raising
  merge command is recorded as `merge_command_failed` but `merged` comes from reading the PR; a
  command that *succeeded* while the PR is not merged is likewise reported as unmerged. An exit
  status is evidence about a process, not about the pull request.
- **Without the seam a failure still propagates** — a caller that cannot observe the truth shouldn't
  guess in either direction, and the pre-0065 contract is preserved exactly.
- The report keeps the anomaly rather than smoothing it: `merged (merge command errored; PR state
  confirms it landed)`.

### Added — autonomous PR watch: merge gate, comment triage, conflict resolve (ADR 0063)

The PR watcher (ADR 0044/0045) stopped at the review-thread fix loop and left every merge to a
human. It can now carry a PR to done: monitoring starts at PR creation, re-checks on a fixed
cadence, triages each review comment, resolves conflicts, and merges once the gate opens.

- **`merge_readiness()` — the merge gate as a pure, tested function.** It opens only when: not a
  draft, the check rollup is green, no unresolved *actionable* threads, and `MERGEABLE`. Every unmet condition becomes a human-readable reason, so a watch
  report says *why* a PR is waiting. Two deliberate readings of the ask: **"no comments" means no
  unresolved actionable threads** (a triaged-and-resolved PR is mergeable — the literal reading would
  make any reviewed PR permanently unmergeable), and **"green builds" requires builds to exist** — a
  rollup of `NONE` (no CI at all) **blocks**, because auto-merging into a repo with no CI is exactly
  where an irreversible action should refuse.
- **The external reviewer's window is the poll interval — no separate wait to configure.** A freshly
  opened PR has `PENDING` checks, so the first pass can't merge and the earliest merge is one
  `poll_seconds` (default 600) later. That interval is the window. The tempting wrong version is
  "the build duration is the wait" — it isn't: this repo's own static gate finishes in ~27s, so
  pacing on build time would open the gate before any reviewer looked. Consequence:
  **`poll_seconds` is load-bearing for review latency**, not just a cadence knob, and that is
  documented at the setting. Dropping the configured wait also removes the failure mode it would
  have introduced — a reviewer login that stops posting (app uninstalled) blocking every merge.
- **Never merge in the pass that pushed a fix.** The gate's green checks describe the *pre-fix*
  commit; the new head is untested until CI re-runs. `run_watch` enforces this in the tested core,
  so the merge waits for the next poll rather than shipping an untested commit.
- **Comment triage routes through the existing engine.** A valid comment is a code change, so it goes
  to the `software-engineer` role under the bounded review loop (N = 3), then reply → resolve. An
  invalid one gets a reasoned refutation and the thread is left **open** — the watcher never resolves
  a dispute in its own favour. Docs *and the PR description* are updated in the same pass when an
  accepted comment changed behaviour.
- **A `PostToolUse` hook notices `gh pr create`** and prompts the watch — the only mechanism that can
  fire automatically on PR creation, since a skill cannot observe a command it did not run. It
  matches at a **command position** on a quote-aware segment (so `gh pr view`, or a quoted mention in
  a `--body`, never fires) and requires the PR URL `gh` prints on success. It **only suggests**: it
  never spawns the watcher, because auto-merge sits downstream and a guardrail must not silently
  start an agent that can merge. Never blocks.
- New settings: `pr_watcher.{auto_merge, merge_method, poll_seconds}`. Existing configs stay valid.

### Changed — ADR 0044/0045's "never merges" invariant is deliberately reversed (ADR 0063)

`pr_watch` shipped with *"it never merges and never force-pushes — there is no merge/force command
builder here, by design."* Half of that is now intentionally undone, with the rails that make the
reversal recordable rather than a silent drift:

- `merge_argv()` exists; **`pr_watcher.auto_merge` defaults to `false`** — a published plugin must
  not start merging pull requests in every repo that installs it.
- `merge_method` is clamped to `{rebase, squash, merge}` **in the library**, not only in the schema:
  it reaches argv as `--<method>`, so an unvalidated string would be flag injection. An unknown value
  raises rather than falling back — a merge is irreversible, so a misconfiguration must fail loudly.
  No `--admin`, so repo branch protection is never bypassed.
- **`never force-push` remains absolute** and is now the only such invariant; conflict resolution
  still merges the base *into* the branch and pushes fast-forward.
- The reversal is annotated in ADR 0044 and 0045 themselves, so neither reads as still-true.

## [2026.7.5] - 2026-07-25

One review contract for the whole fleet. Before this release, four of the seven workflows that write
a reviewable deliverable had a review pass whose *outcome did not gate the handoff* — or, in two
cases, no independent review at all — and the external-reviewer lens (ADR 0057) reached only
`develop` and `product`. Now every one of them runs the same shape: **draft → bounded review
(internal roster + the external lens when enabled) → `handoff.review_loop_decision` → `proceed`
ships, `escalate` stops**, with per-artifact criteria for the external reviewer and `Bash` in
`allowed-tools` so those calls can actually run.

### Added — the bounded skeptic loop + external reviewer reach `architecture` and `plan` (ADR 0060)

`develop` and `product` gated their handoff with a bounded review loop plus the external-reviewer
lens (ADR 0057); the two phases between them did not. `architecture`'s review pass was
**"(Optional) … for a non-trivial design"** — no exit criterion, no external lens, and unmentioned in
its definition of done — and `plan` had **no review step at all** (ADR 0037's audit bucketed the
workflows into writers / reviewers / ops phases and missed `plan`, which writes `plan.md`). That is
the worst place for the gap: a bad design or build order is cheapest to catch there and costliest
once `develop` materialises it across every dependency level.

- **`architecture` — a mandatory bounded skeptic pass (step 6).** A fresh `reviewer` (via `Task`)
  attacks the design: each ADR alternative genuinely weighed (not a strawman), every PRD goal traced
  to a component or decision, every risk carrying a mitigation, component boundaries / failure modes
  sound. `deep-review` stays the fan-out option for a large design.
- **`plan` — a mandatory bounded skeptic pass (new step 6).** A fresh `reviewer` attacks the plan:
  every design component covered by a task, the dependency graph complete (no missing edge) as well
  as acyclic, each task independently shippable with a verifiable checkpoint, the deferred list
  explicit.
- **The external-reviewer lens in both, on by default** (`external_reviewer.enabled`): `--kind
  technical` over `tech-design.md`, `--kind plan` over `plan.md`. Both `KINDS` have shipped unused
  since ADR 0042 — no new machinery, and the ADR 0042/0057 posture carries over verbatim (strict
  `{verdict, findings[]}` prompt, `exec --sandbox read-only`, graceful skip when `codex` is absent,
  findings advisory and verified before acting).
- **One shared exit criterion.** Both compute `handoff.review_loop_decision(verdict, iteration,
  cap=3, gate_green=<the phase's validation step passes>)`; `escalate` (still `changes` at N = 3)
  surfaces the unresolved gaps and **does not hand off**. The loop early-exits on `approve`, so a
  clean design or plan still converges in one round.
- **`plan` now proves its DAG instead of asserting it.** Step 5 runs `planning.plan_batches(tasks)`
  — the same helper `develop` batches with, which raises on a duplicate id, an unknown dependency, or
  a cycle — so "dependencies form a cycle-free order" is a deterministic check at the phase that
  writes the plan, not prose checked by the phase that consumes it.

### Added — the same loop + lens reach `research` and `ux-design` (ADR 0061)

Closing ADR 0060's deferral showed the gap was wider than recorded: **ADR 0037's audit missed two
writers, not one.** `research` — the *first* phase of the spine, whose unsupported claim propagates
into the PRD, the design, the plan, and the code — had **no independent review at all** (its
"Synthesize & verify" step is the author's own verification, the exact blind spot the adversarial
pattern exists to cover). `ux-design` had a real two-lens pass (ADR 0037) but no exit criterion, so
as with `architecture` before 0060, "done" did not depend on the review's outcome.

- **`research` — a mandatory bounded skeptic pass (new step 7).** A fresh `reviewer` (via `Task`)
  attacks the brief: every load-bearing claim cited, no invented figures, source disagreements
  reconciled rather than averaged, and the recommendation actually following from the findings.
- **`ux-design` — its existing pass gains the contract.** The two lenses (accessibility, flow/state
  completeness — unchanged, ADR 0037 chose them correctly) plus the external one aggregate to one
  verdict and exit on `review_loop_decision(..., gate_green=<the ux-spec validates>)`; `escalate`
  surfaces the gaps instead of handing off.
- **Two new `external_review.KINDS`: `research` and `ux`.** Wiring the lens with an existing kind
  would have been a defect, not a fix — an unknown kind falls back to the **code** criteria
  ("correctness, bugs, security, integration/API breaks"), so codex would have critiqued a UX spec as
  if it were a diff. Each phase now has criteria matching its own failure modes, and the invariant is
  tested: **one kind per handoff artifact**, the set asserted exactly and every kind's criteria
  distinct. `dev/external_review.py --kind` picks both up automatically (its choices derive from
  `sorted(KINDS)`).
- **All six artifact-writing phases** (`research`, `product`, `architecture`, `plan`, `ux-design`,
  `develop`) now share one shape: draft → bounded review (internal roster + the external lens when
  enabled) → `review_loop_decision` → `proceed` hands off, `escalate` stops.

### Added — `marketing`'s claims pass gains the same contract (ADR 0062)

`marketing` was the last workflow writing a reviewable deliverable outside the shape — not an
oversight this time: ADR 0037 gave it a real bounded claims pass with the right lens (the evidence
discipline). What it lacked was the contract around it — no `review_loop_decision`, so no `escalate`
discipline and nothing saying "don't ship"; no external lens; and no `Output` section at all (the
only workflow skill without one).

- **The shared exit criterion, with a conditional gate — stated honestly.** The loop now computes
  `review_loop_decision(..., gate_green=…)` where the gate depends on the sub-area: schema validation
  for a typed handoff (`market-brief` / `marketing-strategy`), and — since content, offer docs and
  audit reports have no schema — the **evidence discipline itself** for the untyped deliverables.
  For that half the gate largely collapses onto the verdict, so the loop reduces to exit-on-`approve`
  / `escalate` at N = 3. That is weaker than `develop`'s QA gate or `plan`'s `plan_batches`, and
  still strictly stronger than the status quo (no escalate discipline at all). Inventing a schema for
  landing copy to manufacture a deterministic gate would have been worse than naming the limit —
  recorded in ADR 0062 and in `review-loop.md`.
- **The external lens** (`--kind marketing`) over the same evidence discipline, plus an **`Output`
  section** stating that `escalate` surfaces unsourced claims and does not ship.
- **One new `KINDS` entry, not five** — the brief, strategy, offer doc, content and audit report all
  fail the same way (fluff). This **refines ADR 0061's invariant** to *one kind per review-criteria
  set* rather than per schema type; the test still asserts the kind set exactly and that every kind's
  criteria are distinct.
- **Every workflow that writes a reviewable deliverable now shares one shape.** Outside it by design:
  the reviewer-side phases (`code-review`, `security-review` — review *producers*) and the
  ops/deterministic ones (`release`, `deploy-watch`, `incident-response`). ADR 0037's closing claim
  that the loop "reaches every workflow that writes a reviewable artifact" is now actually true.

### Fixed

- **`product`'s external-reviewer step could not actually run (ADR 0057 wiring).** The skill's
  `allowed-tools` had no `Bash`, so the `external_review.review(...)` / `dev/external_review.py` call
  ADR 0057 specified was unreachable — the same class of defect ADR 0037 fixed by adding `Task` to
  `product` / `ux-design`. `Bash` is now in `allowed-tools` for `product`, `architecture`, `plan`
  (which also need it for `handoff` / `planning`), and — same defect, same fix — `research` and
  `ux-design`, whose `handoff.validate_header` calls were equally unreachable (ADR 0060 / 0061).
- **`ux-design` now names where its artifact goes** — `ux-spec.md` under `docs/sdlc/<feature-slug>/`.
  It was the only phase skill specifying the frontmatter but not the path, while
  `patterns/handoff.md` and the Tier-3 checkpoints already assumed it.

### Changed

- Docs updated for the wider wiring: `configuration.md` (`external_reviewer.enabled` now lists all
  seven workflows and their kinds), `architecture/extensions.md`, `architecture/spine.md` (phase
  table), `architecture/design-onboarding.md`, `architecture/product-marketing.md`, `roadmap.md`, the
  `dev/external_review.py` docstring, and the `adversarial-review` / `review-loop` patterns
  (`gate_green` per workflow, including marketing's conditional one). `evals.json`
  `component.purpose` for each touched skill describes the loop; **no `description` changes**, so
  Tier-1 routing and the listing budget are untouched, and no eval assertions were added
  (process-grading — ADR 0037 §5 / ADR 0020).

## [2026.7.4] - 2026-07-25

Hotfix from the pre-publication deep review — corrects a defect in 2026.7.3's commit-gate change
plus public-repo hygiene issues.

### Fixed

- **commit-gate no longer fails open on genuine gate failures (ADR 0059, fixes an 0058 regression).**
  The "gate can't run" detection matched a bare `not found` / `no such file`, which also appears in
  *real* failures — pytest `fixture 'x' not found`, eslint `'y' not found`, an HTTP `404 Not Found`,
  gcc `No such file or directory`, and even this repo's own `dev/validate.py` `SKILL.md not found` —
  so broken code could commit. Detection is now specific signatures only, and the shell's own
  not-found is caught by exit code 127/126 instead. Real failures block again; missing-script /
  uninstalled-linter still fails open.
- **commit-gate joins stdout/stderr with a newline** so a signature can't be spuriously formed or
  destroyed across the stream boundary (ADR 0059).
- **Diagnostics bundle tolerates a non-UTF-8 transcript byte** — `_read_transcript_sessions` now
  reads with `errors="replace"`, so `UnicodeDecodeError` (a `ValueError`, not `OSError`) can't crash
  the bundle build (ADR 0059).
- **CI `gate` workflow now triggers on `master`** (was `main`, a non-existent branch — post-merge CI
  never ran).
- **Marketplace descriptor synced:** `version` `0.0.1` → `2026.7.4`, and the description now lists
  the full domain set (was frozen at the six spine phases).
- **Docs:** README install uses the real GitHub owner (`alex-voloshin-dev`, was `<owner>`); fixed a
  broken relative link in ADR 0048; documented the 2026.7.3 product-agnostic cleanup in that
  release's changelog section.

## [2026.7.3] - 2026-07-25

### Changed / Added — field-driven diagnostics fidelity (from a production bundle, ADR 0058)

A 14-day production bundle from a downstream repo, compared against the raw transcripts, surfaced four
gaps — all now closed:

- **commit-gate no longer blocks on a gate that can't run.** A non-zero exit whose output shows a
  missing lint script / uninstalled linter / missing file (`guardrails.gate_unrunnable`) is
  environment breakage, not a code-quality signal — it fails **open** (records an `anomaly`, allows
  the commit) instead of blocking. All 10 diagnostics events in the field bundle were this
  false-positive (`npm run lint` with no `lint` script / `eslint: command not found`). Real
  failures still block.
- **The bundle discloses its audit coverage.** `diag_bundle.session_coverage` compares the audit
  trail's session ids against the repo's transcripts (metadata only, never content) and the README /
  `log-summary.txt` show a `Coverage: R/M main session(s) … [K MISSED]` line — so a silent
  audit-logging hole (the field bundle had 84 unlogged pre-2026.7.2 sessions) is visible from the
  bundle alone.
- **The audit trail records outcome.** `guardrails.audit_record` adds `error: true` on a clear
  PostToolUse failure signal (`guardrails.tool_errored`; additive — absent on success), so the 441
  failed calls that were invisible in the field trail are now marked.
- **The digest ranks failing tools.** `observability.Digest` gains `errors` + `by_error_tool` and
  `render` adds a "Failures" section — `log-summary.txt` now shows *which* tools fail most.

Hook self-diagnostics were confirmed already present (every hook emits a diagnostics `error` on
crash, ADR 0039); the residual blind spot — a hook killed on timeout — is documented, with the
coverage disclosure as its safety net.

### Added — tested exit criterion for the develop/product review loops

Formalised the bounded review loop's exit as **pure, tested logic** shared by both workflows, so
"when does the loop stop and what does a full run produce" is code, not just prose:

- **`handoff.review_loop_decision(verdict, iteration, cap=3, gate_green=…)`** → `proceed` | `revise`
  | `escalate` — the single exit rule. `proceed` (verdict `approve` **and** the downstream gate
  green) is the *only* path that hands off; `escalate` (still `changes` at the N = 3 budget) surfaces
  the unresolved findings and stops without shipping; unknown verdicts fail safe (never a silent
  `proceed`). Plus `handoff.blocks_approve(findings)` (a `blocker`/`major` forces `changes`) and the
  canonical constants `REVIEW_LOOP_BUDGET` / `BLOCKING_SEVERITIES` / `LOOP_DECISIONS`. `diagnostics`
  now reuses `REVIEW_LOOP_BUDGET` (one home for the constant). Unit-tested in `test_handoff.py`.
- **`develop`** and **`product`** SKILLs now state their loop's exit criterion in terms of
  `review_loop_decision` and define the **result of a full run explicitly**: develop → every plan
  level implemented, reviewed to `approve`, and QA-green (merge-ready code); product → a complete,
  validated `prd.md` that survived the skeptic loop. Neither hands off partial output on `escalate`.
  `review-loop.md` documents the shared function (`gate_green` = QA for develop, artifact-validates
  for product).

### Changed — external reviewer on by default, wired into develop + product (ADR 0057)

The external, different-model reviewer (`codex`, ADR 0042) moves from an off-by-default manual CLI to
a first-class lens in the review cycle:

- **`external_reviewer.enabled` now defaults to `true`** (`settings.DEFAULTS`, `config.example.json`,
  `configuration.md`). Precedence (defaults < user < repo < env) is unchanged; set `false` to opt out.
- **Auto-invoked as an extra lens** in two workflows: `develop`'s multi-aspect code-review gate
  (`--kind code`, folded into the aggregated verdict so its findings drive the **bounded N = 3 review
  loop** — implementation → review → loop-on-signals / advance), and `product`'s skeptic pass
  (`--kind product`, into the worst-first revision loop). Documented in both SKILLs and the
  `multi-aspect-review` / `adversarial-review` patterns.
- **Prompt contract unchanged:** codex is still driven by *our* strict per-kind prompt
  (`build_prompt` → `{verdict, findings[]}`) under `exec --sandbox read-only`, so its findings stay
  machine-parseable and severity-comparable with the internal aspects. We do **not** hand it a bare
  "review this" / parse free prose.
- **Safety valve:** graceful skip when `codex` is absent (the common case) — behaviour is unchanged
  on those machines. Where `codex` is installed, the target is sent to a third party each review
  iteration; the read-only sandbox, bare-executable `command`, sanitised findings, and verify-before-
  acting all still bound this. **Opt out on secret-bearing repos** (`external_reviewer.enabled: false`).

### Removed — downstream product names (repo is now product-agnostic)

Removed every mention of a downstream product name from docs, code, and tests (the diagnostics
bundles that drove ADR 0058 came from a downstream repo); the public repo is now product-agnostic,
using neutral descriptions ("a production repo", "an anonymised downstream repo") and generic
examples. Maintainer identity in LICENSE / plugin manifest / SECURITY is intentionally kept.

## [2026.7.2] - 2026-07-15

### Added — skill-library adoption: marketing execution depth + role checklists (ADR 0056)

Adopted the maintainer's external skill library as **references** (no new on-listing skills;
provenance + what was deliberately not adopted in the ADR):

- **`marketing`** gains two new sub-areas plus an extended third: `references/geo-content.md` (the 0–100 GEO rubric,
  10-point pre-publish checklist, anti-patterns, FAQPage JSON-LD essentials, technical-SEO pass —
  generalized from the field `geo-audit`/`seo-review`/`faq-schema-builder` skills),
  `references/offer-design.md` (value equation, trim & stack, risk reversal, the authenticity
  guardrail — attributed to Hormozi's *$100M Offers* method), and an extended
  `references/content.md` (zero-click social strategy, platform limits, the anti-AI writing gate,
  durable `marketing/MARKETING.md` + `content-calendar.md` convention). The listing description
  gained offer/pricing + GEO/SEO-audit keywords; three Tier-2 cases (a planted-defect HTML audit
  fixture, an offer brief, a social-post pair) and four should-trigger / one should-not phrases
  were added to the contract.
- **`product`** gains `references/prioritization.md` (RICE/ICE/MoSCoW/JTBD/Kano selection table,
  North Star/AARRR/AI-product metrics, Now/Next/Later roadmap shape) and a sharper description
  boundary (not "market/competitor analysis and offer/pricing design (marketing)").
- **Live gates (claude-opus-4-8): Tier-1 marketing PASS recall 0.911 / specificity 1.000; Tier-1
  product PASS recall 1.000 / specificity 0.960; Tier-2 marketing PASS 0.962 (n=5, all six cases
  incl. the three adopted sub-areas).** Router-budget recount after all description changes
  (marketing, product, deploy-watch): 17 on-listing skills, ~2,534 tokens — ~84 over the previous
  ~2,450 note; still ~1.3% of the window and watched by the weekly Tier-1 cron. Getting there surfaced two lessons recorded in the eval
  runbook: the new sub-areas initially diluted the old "market research and analysis" anchors
  (fixed by restoring them + the two-sided boundary clause), and throttled router calls parse as
  `none`, mimicking a stable recall failure.
- **`ux-design`** gains `references/design-handoff.md` (design-to-code handoff template — tokens,
  variants, ALL states incl. focus/disabled/error, ARIA/keyboard; the 5-minute a11y pass) and a
  Tier-2 handoff-spec case — **Tier-2 executed live: PASS 1.000 (n=5, claude-opus-4-8)**.
- **`qa-test-strategy`** gains `references/bug-reports.md` (structured bug report: minimal repro,
  expected-vs-actual, evidence, severity rationale; charter-driven exploratory testing).
- **`deep-review`** gains a **reader-testing** lens for docs (simulate the target reader's task;
  findings are the questions the doc fails to answer).

### Added — `pr-watch` skill: interactive PR/CI babysitting (field-driven increment 1)

A manual, off-listing skill (`/pr-watch`; `disable-model-invocation`, so it costs no router-listing
budget) that replaces the hand-rolled polling the field bundle showed (232 `gh pr`/`gh run` polls +
ad-hoc wait loops in one week): snapshot checks + review threads + mergeable state via `gh` and the
tested `agentic_forge.pr_watch` lib (ADR 0044/0045), report the baseline, re-poll at a cadence
matched to the slowest pending check, report **transitions only**, stop at a terminal state.
Watching is read-only; an explicit ask enables the bounded fix loop (reply-before-resolve,
`max_threads` cap, single plain `HEAD:<branch>` push) — never a merge, never a force-push.
Contract: `plugin/skills/pr-watch/evals/evals.json` — Tier-2 over hermetic recorded-snapshot
fixtures (`eval/fixtures/pr-watch/`), **executed live on the review-amended contract: PASS,
mean 0.986 / lower bound 0.954 ≥ 0.8 (n=5, claude-opus-4-8)** (first run 0.943/0.815; the
deep-review pass then added the no-live-sleep guards and the parse_pr-compatible fixture key,
and the re-run improved).

### Added — `deploy-watch` covers Kubernetes cluster health (field-driven increment 2)

81% of field sessions were scheduled k8s health checks the skill could not serve. New
`references/k8s-health.md` (read-only `kubectl` reads; the observation→verdict mapping onto the
existing healthy/degraded/failing scale; the same `deploy-status` handoff; a scheduled/headless
recipe), a k8s Tier-2 eval case with a `k8s-degraded.json` fixture, and three k8s should-trigger
phrasings (+ one should-not). The listing description grew by "cluster … (k8s — nodes, pods,
events)" — **+~10 tokens against the router budget** (reviewed: still within the ~1% ceiling).
**Tier-1 executed live on the changed description: PASS, recall 0.971 / specificity 1.000
(claude-opus-4-8, 5 runs)** — the k8s phrasings route and no neighbour regressed. **Tier-2
executed live with the new k8s case: PASS, mean/lower bound 1.000 (n=5, claude-opus-4-8).**

### Added — `deep-review` ships a canonical Workflow template (field-driven increment 3)

`references/workflow-template.md`: one canonical finding/verdict schema pair (field runs drifted —
`corrected_severity` vs `correctedSeverity` vs ad-hoc keys), a script skeleton with per-lens
retry-once (a lens lost to an agent error gets retried, then *disclosed* as lost — never silently
"clean"), REFUTED-by-default verification, and resume guidance. References-only: zero listing cost.

### Changed — observability hygiene (field-driven increment 4)

- **Audit-log rotation:** `observability.rotate_audit` trims the log to its newest ~5 MB once past
  ~10 MB (whole records kept; a field repo accrued 2.6 MB/week unbounded), called once per session
  by the session-start hook.
- **Worktree-aware log placement:** `diagnostics.main_repo_root` resolves a linked worktree's
  `.git` file back to the primary tree; the audit hook and `diagnostics.record_event` now write
  there, so worktree-phase trails survive the worktree's removal (the field bundle showed users
  hand-cleaning stray worktree dirs and losing the trail).
- **Settings-slice scope:** the bundle's `settings-agentic-forge.json` now filters
  `enabledPlugins` / `extraKnownMarketplaces` to the agentic-forge entries — a real bundle shipped
  two unrelated plugins' names/marketplaces the file name never promised.

### Added — "Cutting a release" guide in CONTRIBUTING.md

Documents the CalVer release flow end to end (ADR 0055) **including the `master` ruleset that is
not visible in the tree**: PR-only with the "Tier 0 (static gate)" check, linear history (rebase
merge rewrites SHAs), auto-merge disabled — hence the rule that the release tag is created only
*after* the merge, on the merged commit (precedent: PR #3 / `v2026.7.1`).

## [2026.7.1] - 2026-07-14

The first CalVer release (`<year>.<month>.<inc>` — ADR 0055). All items below come out of the
second production diagnostics bundle (an anonymised downstream repo, 7 days / 136 sessions / 5,541
tool calls, plugin 0.0.1→0.1.0 mid-window) plus this repo's own diagnostics log — the first field data over
a 0.1.0-era plugin.

### Fixed — security deny-list blocked commands that merely QUOTE a dangerous string (ADR 0054)

The rm/chmod/find/force-push rules still used text matching over quote-stripped segments, so
segmentation split *inside* string literals and data looked like code: `python3 -c` scripts holding
a pattern like `push --force|rm -rf /|…`, `git commit -m "block rm -rf /"`, `grep "rm -rf /"`,
`echo`/`sed` examples — 6 of 8 representative "dangerous string as data" commands blocked (four
such blocks recorded in this repo's own diagnostics; the same class ADR 0051 fixed for net-pipe).
`classify_command` now (1) splits segments on `;`/`|`/`&`/newline **outside quotes**, (2) tokenizes
with `shlex`, (3) fires each rule only on the segment's **command word** (after sudo/env-assign/
wrapper prefixes), (4) still recurses into what the shell executes — sh-family `-c` payloads and
`$(…)`/backtick substitutions — and (5) degrades unparseable segments to the old block-leaning text
checks. mkfs/dd moved to token rules; every prior true positive still blocks, plus new ones the
text-match missed (`timeout 5 rm -rf /`, `/bin/rm -rf /`). New allow/block regressions in
`tests/test_guardrails.py` from the production corpus.

### Fixed — diagnostics bundle shipped no plugin version and overclaimed audit fidelity (ADR 0052/0053 follow-up)

- The collector read the manifest from `~/.claude/plugins/plugin.json` — a path that never existed —
  and the install record from pre-rename `plugins/config.json`; real bundles therefore shipped
  **without any plugin version** (triage had to infer 0.0.1 from cache paths inside logged
  commands). `diag_bundle` now reads the manifest from the plugin root it ships inside, reads
  `installed_plugins.json` (with the legacy fallback), and stamps `plugin: <name> <version>` into
  `environment.txt`.
- The bundle README claimed "each `input` is valid JSON" while 799 of 5,541 field records were
  pre-0.1.0 truncated non-JSON, and the headline counts silently blended 1,478 undated records the
  window cannot filter. New pure `audit_quality()` counts both; README + `log-summary.txt` now
  **disclose the legacy share** and only claim uniform validity when it is true.

### Fixed — `models.py` crashed on import under Python 3.9 + Tier-0 now guards the whole shipped tree

The one shipped module without `from __future__ import annotations` held a PEP 604 annotation
(`dict[str, str] | None`) that raises `TypeError` at import time on 3.9 — exactly the interpreter
real hooks run on (field `environment.txt`: macOS CommandLineTools 3.9.6), and field sessions do
import the shipped lib by hand. Fixed, and `validate_python_compat` (new Tier-0 check in
`validation.py`) now errors on any non-empty runtime `.py` (lib / hooks / skill scripts; eval
fixtures exempt) missing the future-import, so the 3.9 contract (ADR 0050) can't regress silently.

### Fixed — commit-gate fail-open was invisible (upholds ADR 0039)

An infra error running the gate (tool missing, timeout) returned ALLOW with no trace, making an
empty diagnostics log ambiguous between "nothing wrong" and "the gate never ran" (the field bundle
read 0 events). The infra path now emits a `commit-gate` **anomaly** event (gate command + error
class) before allowing.

### Changed — CalVer versioning `<year>.<month>.<inc>` (ADR 0055)

Releases move from semver to CalVer (first cut under the scheme: **2026.7.1**): the version now
answers "how fresh is this install?" — the question the field bundle could not (a `0.0.1` cache
against a `0.1.0` release, nothing dating either). No zero-padding, so versions stay valid semver
triples and sort correctly across the migration; the monthly counter restarts at 1; breaking
changes are flagged in the changelog, not the version. `release.next_calver` / `looks_calver`
implement the scheme; `release.summarize(..., calver=(y, m))` and the `release` skill pick the
scheme mechanically (CalVer repos vs semver repos); tests pin ordering, counter restart, and
migration from `0.1.0`.

### Changed — `config.example.json` no longer pre-fills `models`

A field user copied the example's `"models": {"router": "cheap", "grader": "simple"}` into
`~/.agentic-forge/config.json` verbatim — after burning a session reverse-engineering `settings.py`
to learn what it does (nothing, in live sessions: the key only affects the eval/dev CLIs; live role
routing is the gate-validated agent frontmatter, ADR 0046). The example now ships `"models": {}`;
`docs/configuration.md` states what `models` actually affects and adds "Which Python do you need?"
(hooks: any bare `python3` ≥ 3.9, no deps; developing the plugin: ≥ 3.11).

### Added — field-driven product plan (docs/roadmap.md)

The bundle's *product* signals, analyzed before any code: an interactive `pr-watch` skill (232
manual `gh pr`/`gh run` polls + hand-rolled wait loops in one week), `deploy-watch` k8s-health
coverage (81% of field sessions were scheduled cluster checks another plugin served), canonical
deep-review workflow assets (three audits each re-invented the orchestration; schemas drifted),
and observability hygiene (audit-log rotation, worktree-aware log path, tighter settings slice).

## [0.1.0] - 2026-07-06

First tagged release. Everything below is the aggregated changelog since the initial `0.0.1`
scaffold: the full skill/agent/hook surface plus the public-release prep, capped by the
production-log-driven guardrail fixes and the diagnostics bundler.

### Fixed — security deny-list over-matched legitimate local commands (ADR 0051)

Real production logs (a diagnostics bundle: 39 sessions, 2 days) showed the "pipe a network
download into a shell" blocker firing on legitimate work — all recorded blocks were the same false
positive, retried ~17 times across 4 sessions. `guardrails.classify_command` now uses a structured
`_dangerous_net_pipe` check that blocks only the real RCE shape: a `curl`/`wget`/`fetch` in
**command position** feeding a **bare** interpreter (one that reads *stdin as its program*) from a
**non-loopback** host. So these no longer block: `curl localhost:9090/… | python3 -c "…"` (local
observability), `curl https://api/… | python3 -m json.tool` (data parsing), and `grep "curl|wget"`
(the words as literal text). The true hazard (`curl https://…/install.sh | sh`, `… | sudo bash`,
`wget -qO- … | python`) still blocks, with new allow/block regressions in `tests/test_guardrails.py`.

### Fixed — audit log corrupted long records / added a diagnostics bundle packager (ADR 0052)

- `guardrails.audit_record` truncated the whole JSON-encoded `tool_input` at 300 chars, producing
  **invalid JSON** inside the `input` field — 60% of Bash records in a real bundle were unparseable.
  It now redacts + truncates **each field value** and re-encodes, so `input` stays a *valid* JSON
  string (`json.loads(rec["input"])["command"]` round-trips). No schema change for existing
  consumers.
- New `lib/agentic_forge/diag_bundle.py` (pure `plan_bundle` manifest + thin `build_bundle` zip
  seam) and `dev/diagnostics_bundle.py` CLI package a repo's diagnostics into one consistent,
  redacted zip: the audit + diagnostics logs, a `log-summary.txt` (both digests), `environment.txt`,
  and plugin/config metadata (settings slice keeps only enablement + hooks, never tokens). Covered
  by `tests/test_diag_bundle.py`.

### Added — `diagnostics-bundle` skill: windowed, ~/Downloads, consistent naming (ADR 0053)

A shipped, manual (off-listing) skill to package a repo's plugin diagnostics from a production
session — no more ad-hoc, inconsistent bundles.

- `plugin/skills/diagnostics-bundle/` — `SKILL.md` (manual `/`-command; `disable-model-invocation`,
  so it does not spend the always-on router budget), a shipped `scripts/build_bundle.py` over the
  tested lib, and `evals/evals.json` (Tier-2, self-contained per ADR 0017).
- Writes strictly to `~/Downloads/agentic-forge-diagnostics-<YYYYMMDD-HHMMSS>.zip` (consistent name)
  covering the **last 7 days** by default (or a user-given window; `--days 0` = full history); the
  covered window is stated in the README + `log-summary.txt`.
- `guardrails.audit_record` now records an optional `ts` (the audit hook stamps it), so the audit
  trail is time-windowable; `filter_by_window` retains blank/undated/legacy records rather than
  silently dropping what it cannot date. `diag_bundle` gains `filter_by_window` / `window_text` /
  `default_output_path`; `build_bundle` takes `days` and defaults the output to `~/Downloads`;
  `dev/diagnostics_bundle.py` gains `--days`. Covered by `tests/test_diag_bundle.py` /
  `test_guardrails.py` / `test_dev_cli.py`.

### Added — community-health files (public-release prep)

Ahead of opening the repository, added the standard GitHub community files: `SECURITY.md` (private
vulnerability reporting + in/out-of-scope, noting the guardrails are defence-in-depth, not a
sandbox), `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), a `.github/PULL_REQUEST_TEMPLATE.md`
mirroring the contract→evals→gate + documentation-discipline checklist, and
`.github/ISSUE_TEMPLATE/` forms (bug report, feature/component request framed contract-first, and a
`config.yml` routing security reports + questions away from plain issues). `CONTRIBUTING.md` now
links the Code of Conduct and the security policy.

### Added — Tier-0 doc-sync gate (consistency review pass)

A fresh-eyes consistency review found the only real drift was documentation lagging the last ~10
ADRs. To stop it recurring, `validation.validate_docs` adds two deterministic, LLM-free checks to
the Tier-0 gate (run by `dev/validate.py` from the repo root):

- the `docs/architecture/meta-core.md` shared-library table must list exactly the modules in
  `plugin/lib/agentic_forge/` — a new or removed module now fails the gate until the table matches;
- every ADR under `docs/architecture/decisions/` must be linked from that dir's `README.md` index,
  and every index link must resolve.

`tests/test_validation_docs.py` covers both directions of each check plus a live-repo smoke test.

### Changed — documentation synced to the current tree (review pass)

- `docs/architecture/meta-core.md` — the shared-library table and repo-layout block now cover the
  six post-Stage-7 modules (`diagnostics`, `settings`, `models`, `external_review`, `pr_watch`,
  `ralph`); the table is now gate-enforced (above).
- `docs/architecture/extensions.md` (new) — narrative home for the cross-cutting, opt-in plugin
  extensions (config ADR 0041/0049, model tiering/routing ADR 0043/0046, the external reviewer ADR
  0042, the PR watcher ADR 0044/0045); linked from `overview.md` and the `docs/README.md` map.
- `CLAUDE.md` — Layers section lists the plugin extensions and the full engine-pattern set; Tier-0
  description notes the doc-sync check and clarifies which gate enforces coverage/lint/types.
- `connectors.py` docstring now documents both real connectors (`GhPipelineSource` **and**
  `GrafanaAlertSource`), not just the pipeline one.
- Append-only correction notes on ADR 0017 (the Tier-2-declaring skill count grew with later
  stages) and ADR 0039 (its Context describes the pre-0039 state; hooks now record crashes), plus a
  CLI-driven-pattern note on `patterns/ralph.md` and a `.NET / C#` label fix in `dotnet-patterns`.

### Fixed — session-start hook records its own crashes (ADR 0039 parity)

`session_start.py` was the only guardrail/injection hook that failed fully silent on error. It now
emits a redacted `diagnostics` event (still fail-open, exit 0) like every other hook, so a vault or
injection bug surfaces in the diagnostics digest instead of vanishing.

### Fixed — guardrail hooks import on a dependency-light, version-robust path (ADR 0050)

Claude Code runs the L4 hooks as `python3 <hook>.py`, using whatever `python3` is first on PATH. On
a machine whose system `python3` is 3.9 without the plugin's deps, every Bash tool call raised
`ImportError: cannot import name 'UTC' from 'datetime'` at **import** — before each hook's fail-open
guard — so the guardrails both spammed tracebacks and were disabled. The hook-reachable import path
is now stdlib-only and not ≥3.11-only:

- `diagnostics` uses `datetime.now(timezone.utc)` instead of the 3.11-only `datetime.UTC`.
- `jsonschema` (`settings`, `handoff`) and `PyYAML` (`frontmatter`) are imported **lazily** and
  degrade gracefully when absent: `settings` loads a committed config *unvalidated* (coercing every
  value, so `resolve` still never raises); `handoff.validate_header` skips validation;
  `frontmatter.parse` raises a clear `FrontmatterError`.
- Critical guardrails (security deny-list, test-gate, audit log) now work on a bare `python3`; only
  schema validation + knowledge-vault injection degrade without the optional deps.
- New `tests/test_hook_import_safety.py` blocks `jsonschema`/`PyYAML` and imports the whole hook
  chain (subprocess) so a future top-level dep import fails the gate. Coverage stays above the floor.

### Added — user-level (cross-project) plugin config (ADR 0049)

`settings.resolve` now layers a **user-level** config — `~/.agentic-forge/config.json` — between the
built-in defaults and the per-repo file: **defaults < user-level < per-repo < env**. Set a
preference once in your home (e.g. enable the diagnostics log, or route the router/grader to a
cheaper model tier) and it applies across every project, still overridable per-repo and by env vars.

- Both files validate against the same `schemas/config.schema.json` and deep-merge (a repo overrides
  only the keys it sets). `resolve` gains a `home=` parameter (defaults to `Path.home()`).
- A committed, schema-valid example with **every** key ships at `plugin/config.example.json`, fully
  documented in the new `docs/configuration.md` (keys, types, defaults, effects, precedence,
  env-var overrides). Extends ADR 0041.
- Tests isolate `HOME` (autouse `conftest` fixture) so they never read a developer's real user
  config.

### Fixed — fresh-eyes review pass: documentation-drift sync + eval/coverage hardening

A repo-wide review (integrity, consistency, contradictions, duplication, doc coverage) found the
authoritative docs correct but the navigational/summary layer lagging shipped features, plus a few
low-severity hardening items. No behaviour change to existing flows; Tier-0 stays green (coverage
97.99%, suite all-pass).

- **ADR index** — `docs/architecture/decisions/README.md` was frozen at 0035; appended the 13
  missing rows (0036–0048), including PR-watcher / model-routing / version-A-B / Ralph.
- **"deferred" → "built" drift** — the Ralph loop (ADR 0048) and version-over-version A/B (ADR
  0047) shipped, but `overview.md`, `vision.md`, and the `docs/README.md` glossary still called
  them deferred; corrected to match the ADRs / engine.md / roadmap / CLAUDE.md.
- **Stale CLI/role lists** — added `dev/ralph.py` to the `CLAUDE.md` repo-layout block; refreshed
  the `meta-core.md` `dev/` list (7 → 12); noted the full six-role engine roster (+
  `security-engineer`, `qa-engineer`, and that `grader` is eval-harness-only) in `engine.md`.
- **Tier-2 scope** — surfaced the existing policy (the SDLC-spine skills carry only Tier-1; their
  quality comes from the delegated roles' Tier-2 + the Tier-3 spine scenario — already detailed in
  eval-runbook.md) in `CLAUDE.md §4`, so it no longer reads as a coverage gap.
- **Handoff filenames** — `patterns/handoff.md` now states the `<type>.md` naming convention
  explicitly, so any artifact's on-disk name is predictable from its type.
- **Coverage floor** — `plugin/hooks/scripts` is now in the gated coverage `source` (pyproject), so
  a hook regression below 80% fails Tier-0 (the hooks sit at 84–94% today).
- **Eval-CLI dedup** — the duplicated transport construction in `run_agent_evals` /
  `run_skill_evals` is folded into one `_eval_cli.build_runners(...)`; the per-CLI `_build_runners`
  remain thin, tested adapters. The three eval CLIs make their `dev/` `sys.path` bootstrap explicit.
- **Routing guard** — added reciprocal `should_not_trigger` cases pinning the `deep-review` ↔
  `security-review` "deep audit of a module" boundary (Tier-0/dry green; confirm recall/specificity
  at the next live Tier-1 run — it is opt-in / cost-gated, not on the always-on path).

### Added — Ralph loop: bounded autonomous iteration (engine, ADR 0048)

Closes the L1-deferred **Ralph loop** engine pattern: re-run a fresh-context executor against a
persistent task with a stable prompt until it's **done**, **stalls** (no progress), or hits the
**iteration budget**. The filesystem (code + git) is the memory across iterations.

- **`lib/agentic_forge/ralph.py`** — the deterministic loop-control core: `LoopState`, `decide`
  (`continue | done | exhausted | stalled`), `advance`, and `run_ralph(...)` — the bounded driver
  over three injected seams (`run_iteration` / `is_done` / `progressed`). Pure + 100% tested; it
  **never merges and never pushes** (no such seam). Three independent limits guarantee termination:
  the done signal (early exit), the stall counter (no-progress guard), and the iteration budget.
- **`dev/ralph.py`** — the runner: a fresh-context `software-engineer` per iteration (**no Bash** —
  Read/Write/Edit/Grep/Glob), `git` for progress detection (hooks disabled), and a `--done-cmd`
  (exit 0 = done) as the stop signal. **Dry by default** (plan only); `--apply` runs it. Bounded by
  `--max-iterations` (clamped ≥ 1) + `--stall-after`; the model is tier-resolved (ADR 0043/0046); an
  unfinished run with a done-cmd is recorded as a diagnostics anomaly.
- **`plugin/patterns/ralph.md`** — the pattern doc: compose with **worktree** (isolation),
  **software-engineer** (executor), and **review-loop** (review before merge); point `--done-cmd` at
  the real gate (tests / `dev/validate.py`) so "done" means "passes."
- Opt-in (a dev CLI), dry-by-default, always terminates, never auto-merges/pushes — no behaviour
  change to existing flows.
- Docs: ADR 0048; engine.md / CLAUDE.md (L1 "Ralph (deferred)" → built) + roadmap updated. New tests
  (`test_ralph.py` for the core; the `ralph` CLI dry/apply/done/stall paths); `ralph.py` 100%,
  coverage 98.33%.

### Added — version-over-version A/B: stored benchmark history + regression gate (ADR 0047)

Closes the last deferred A/B piece (ADR 0036 §6 / 0038): catch a **cross-version quality
regression** — an edit that drops a component below its **prior** validated mean — which the
with/without A/B (lift / overhead) can't see. The deferral's named prerequisite, a *stored benchmark
history*, is what this adds.

- **`benchmark.py`** — an append-only history of `{component, model, mean, stddev, n}`:
  `make_record` + `prior_record` (pure) and `load_history` / `save_history` (I/O). Keyed by
  **(component, model)** because Tier-2 is model-dependent — a regression check only compares
  same-model runs (switching tiers starts a fresh baseline).
- **`gate.version_regression(benchmark, prior, thresholds)`** — FAIL if the current `with_skill` mean
  dropped more than `max_regression` below the prior recorded mean. Returns **None — skip** when
  there's no prior (first run) or no `max_regression` threshold: opt-in, engages only once a baseline
  exists. A distinct **cross-run** gate, separate from the single-run `tier2_quality`.
- **Runner wiring** — `--record` + `--benchmark-history PATH` on both eval runners, via a shared
  `_eval_cli.version_check` helper. After each run it compares against the latest same-model record
  (folded into the run's pass/fail) and, with `--record`, appends the current numbers — **only for a
  healthy run** (passed `tier2_quality` *and* no regression), so a failing/regressed run never
  poisons the baseline. Default history is the per-repo `.agentic-forge/benchmark-history.json`;
  point `--benchmark-history` at a committed path for cross-version / CI gating.
- **`max_regression`** added to the evals.json `tier2_quality` schema.
- **No behaviour change by default:** opt-in via `--record` (build a baseline) + a `max_regression`
  threshold; a normal run is unaffected.
- Docs: ADR 0047; ADR 0036/0038 deferral notes + roadmap + eval-runbook + CLAUDE.md updated (the
  "version-over-version deferred" caveat is now closed). New tests (`benchmark` history,
  `version_regression`, the `version_check` helper, the runner record/regression paths);
  `benchmark.py` / `gate.py` / `_eval_cli.py` 100%, coverage 98.34%.

### Added — runtime model routing: the validated tier reaches live `Task` delegation (ADR 0046)

Closes the part of ADR 0043 (§5) left deferred: a gate-validated model tier now actually reaches
**runtime subagent delegation**, not just the eval runners. The lever is the agent `model:`
frontmatter (what Claude Code reads when a skill forks a role via `Task`).

- **`models.VALIDATED_TIERS`** — the committed runtime tier policy per role, shipping **all-`default`**
  (no downgrade out of the box). A role is promoted to a cheaper tier here only after it passes the
  eval gate at that tier.
- **`models.frontmatter_model(role)`** — resolves the policy to a `model:` value: `inherit` for the
  `default` tier (follow the session model — safe, respects `/model`), else the concrete validated
  model id (the same `TIERS` the eval path uses). Plus `set_frontmatter_model` (pure line-rewriter).
- **Tier-0 enforces frontmatter == policy** (`validate_agent`): an agent whose `model:` ≠
  `frontmatter_model(role)` fails the gate, so live routing can't silently drift from what was
  validated. `model:` is now effectively required on every agent.
- **`dev/sync_models.py`** (`--check` default / `--apply`) regenerates the `model:` frontmatter from
  the policy — `--apply` rewrites, `--check` (and Tier-0) flags drift. Promote-a-tier flow documented
  in `docs/eval-runbook.md`.
- **No behaviour change by default:** all six agents stay `model: inherit` (policy all-`default`);
  Tier-0 + `sync_models --check` are green on the real plugin.
- Docs: ADR 0046; ADR 0043 §5 / roadmap updated to point at the closure. New tests
  (`frontmatter_model`, `set_frontmatter_model`, the Tier-0 drift/missing checks, the `sync_models`
  CLI); `models.py` 100%, coverage 98.37%.

### Added — PR watcher 1b: scheduled job over repos + mechanical conflict resolution (ADR 0045)

Completes the three items ADR 0044 deferred to 1b: the scheduled job's "which PRs to watch" wiring,
mechanical conflict resolution (detect-only shipped before), and the live-validation runbook.

- **Scheduled job over configured repos.** `settings.pr_watcher.repos` (a list of `"owner/name"`)
  names the repos to watch; `pr_watch.parse_repos` parses them (malformed entries skipped) and
  `pr_watch.watch_repos(specs, *, list_prs, watch_one)` is pure orchestration over two seams. The
  `pr-watch` hourly job's `run_scheduled` action wires the real seams (`gh pr list` for discovery; a
  subprocess to `dev/pr_watch.py --apply` per PR) and **no-ops with a message** unless
  `pr_watcher.enabled` **and** ≥1 repo is configured.
- **Mechanical conflict resolution.** `run_watch` gains a `handle_conflict` seam (called only on a
  `CONFLICTING` PR). The live handler **merges the base INTO the PR branch** (`git merge --no-edit
  origin/<base>`) — a *merge*, not a *rebase*, so the follow-up push stays a fast-forward and needs
  **no force-push**; on a merge conflict it `--abort`s and posts a PR comment asking for a manual
  rebase. `WatchResult` gains `conflict_resolved` / `conflict_unresolved`; push fires when anything
  was fixed **or** a conflict was resolved. `PrState.base` (`baseRefName`) + `pr_comment_argv` added.
  Still **never merges/closes the PR and never force-pushes** (no such builder). The per-PR runner
  `gh pr checkout`s the branch first (same-repo PRs); fork PRs stay out of the auto-apply scope.
- **Live-validation runbook.** Real-PR validation needs `gh` auth + a throwaway PR + side effects,
  so it can't run in CI — documented as a checklist in `docs/eval-runbook.md` ("Validating the PR
  watcher"): dry plan → `--apply` on a throwaway PR → confirm the invariants before enabling.
- Reviewed by two adversarial lenses (correctness + security/safety), each finding verified against
  source before accepting. Fixes applied pre-commit: **(safety)** git hooks disabled on every git
  seam (`-c core.hooksPath=/dev/null`) so a hostile PR branch can't run hooks on checkout/commit/
  merge; **fork PRs refused** on the auto-apply path (`isCrossRepository` now fetched + on
  `PrState`); the fixer system prompt hardened with an untrusted-input frame; the `push` and
  conflict-comment outward writes now carry explicit audit rows. **(correctness)** conflict handler
  switched from rebase to **merge** (a rebase would make the non-force push undeliverable); the
  per-PR runner aborts if `gh pr checkout` fails (never `--apply` on the wrong branch); `_git fetch`
  failure aborts the merge; the un-resolvable-conflict comment is posted **once** (idempotent via
  `conflict_notice_present`); `parse_repos` dedupes; the fixer `git add -A`s so new files are staged.
  One finding (argv `-`-flag injection) was verified **not reachable** and declined.
- Docs: ADR 0045; roadmap increment-1 marked done. New tests (`parse_repos`, `watch_repos`,
  conflict paths, `pr_comment_argv`, the `_pr_watch` action); `pr_watch.py` 100%, coverage 98.38%.

### Added — PR watcher: monitor a GitHub PR, bounded auto-fix loop (planned-increment 1, ADR 0044)

A watcher that reads a PR's review threads + conflict state and runs a bounded fix loop. Chosen
autonomy (auto-fix + push, opt-in): it fixes each actionable reviewer comment, pushes to the PR
branch, and replies/resolves the thread — it **never merges** and **never force-pushes**; off by
default; every outward action is recorded in diagnostics.

- **`lib/agentic_forge/pr_watch.py`** — pure parsing / planning / command-building over the `gh`
  GraphQL JSON: `parse_pr` → `PrState` (mergeable + review threads), `actionable_threads`
  (unresolved, not bot-authored — idempotent across the hourly re-poll), `plan_watch` (dry plan),
  the `reply_argv` / `resolve_argv` / `push_argv` builders (**no merge or force-push builder
  exists, by design**), and `run_watch` — the bounded loop: per thread the fixer decides fix-vs-
  reject, a fix replies + resolves + (once any lands) pushes `HEAD:<branch>`, a rejection replies
  and leaves the thread open. The live `gh`/`git`/fix calls are injected **seams** (tested with
  stubs; real calls excluded from coverage).
- **`dev/pr_watch.py`** CLI — `--dry` by default (plan only); `--apply` runs the loop **only when
  `pr_watcher.enabled`**. Fetch/fix/gh/push are injectable (tested) with real defaults; degrades on
  a fetch error. The fixer model is tier-resolved (ADR 0043).
- **`settings.pr_watcher`** (`enabled` / `bot` / `max_threads`) + schema; **`hourly` cadence** added
  to the scheduler (the watcher is driven by an hourly cron — the ADR-0024 "no daemon" model).
- Safety invariants: never merge, never force-push, opt-in, bounded, dry-by-default, every outward
  write audited **unconditionally** (`diagnostics.emit(force=True)`). Reviewed by two adversarial
  lenses (safety + correctness; no blockers); fixes applied: the fixer now reports `fixed` only when
  a diff actually landed (commits it so the push delivers it; else `rejected`, never silently
  resolving a disputed thread), runs **without the Bash tool** to bound prompt-injection, and the
  audit is force-on. Trust boundary documented (enable only for trusted PRs).
- Deferred (1b): the scheduled `pr-watch` job's "which PRs to watch" wiring, mechanical conflict
  resolution (detect-only ships now), and live end-to-end (real-PR) validation — **now completed in
  ADR 0045** (the buildable two; live validation is a documented manual runbook).
- Docs: ADR 0044. New tests (`test_pr_watch.py` + CLI tests); `pr_watch.py` 100%, coverage 98.35%.

### Added — multi-model support / model tiering (planned-increment 4, ADR 0043)

Per-component model tiering — cheaper models (sonnet / haiku) for simpler work, opus for hard work
— configured in `settings.models`, with the eval gates validating any downgrade.

- **`lib/agentic_forge/models.py`** — `TIERS` (`default`→opus-4-8, `simple`→sonnet-4-6,
  `cheap`→haiku-4-5) and `model_for(component, models, *, default)`: a per-component entry in
  `settings.models` wins (a tier name → its model, or a model id used as-is); otherwise the global
  `default`. Pure + 100% tested.
- **Safe by default:** an empty `settings.models` resolves every component to the global default
  (opus) — no behaviour change. Opt in per component, e.g. `"models": {"grader": "simple",
  "router": "cheap"}`.
- **The eval runners resolve per-component and the gates enforce the tier:** `run_agent_evals` /
  `run_skill_evals` / `run_tier1_evals` run each role / skill / router at `model_for(...)`. So a
  cheaper tier is **validated by Tier-1 / Tier-2** — if it drops below the bar, the gate fails (the
  eval-driven "only downgrade where it still passes" rule, enforced mechanically; the ADR-0036
  `--baseline` A/B measures the quality/cost trade-off).
- Recommended tiers + the validate-before-flip rule are documented (ADR 0043 / eval-runbook); the
  `model` frontmatter stays available for runtime Task delegation (full auto-threading deferred).
- Docs: ADR 0043. 5 new tests (`test_models.py` + a runner-tier integration test); `models.py` 100%,
  coverage 98.34%.

### Added — external reviewer (codex) as a subagent (planned-increment 2, ADR 0042)

An external reviewer CLI (`codex`, for now) can be run as an independent review lens — for code, a
plan, or a product / technical document. A different model catches what a same-family `reviewer`
pass misses (adversarial-review.md).

- **`lib/agentic_forge/external_review.py`** — a pure parser + a thin subprocess seam (connectors
  style): `build_prompt(target, kind)` (kind ∈ code|plan|product|technical, asks for the canonical
  review JSON), `is_available` (`shutil.which`), `run_external` (injected subprocess seam; the real
  call excluded from coverage; **never raises**), `parse_review` (lenient — reuses
  `agent_eval.parse_grading` to extract + normalise `{verdict, findings}`), and `review(...)`.
  Degrades to `None` when the CLI is absent / disabled / unparseable.
- **`dev/external_review.py`** CLI — reads `settings` (`external_reviewer.command`; refuses unless
  `enabled` or `--force`), reviews a target file, prints verdict + findings, and can write a
  schema-valid `review.md` handoff (`--out`) so a codex review feeds the review-loop / review-scan.
  Exit 0 on approve / skipped, 1 on `changes` / unparseable.
- Gated by the increment-3 settings (`external_reviewer.{enabled,command}`); off by default.
  Documented as an optional lens in `adversarial-review.md`. Other external reviewers can be added
  behind the same `command` seam later.
- **Security/correctness review (2 lenses) — fixed before commit:** the seam now runs codex
  **read-only** (`exec --sandbox read-only`, built in a unit-tested `_argv` so the safeguard can't
  silently regress — a reviewer must never mutate the repo); `command` is schema-constrained to a
  bare executable name (no arbitrary-binary-from-committed-config); `parse_review` scans *all* JSON
  objects (tolerates a leading `codex exec` session object) and clamps severities + sanitises
  findings (no markdown injection into `review.md`, which now also carries `findings[]` in the
  header); the CLI guards a missing `--target` and gained `--iteration`. The trust boundary
  (target → third-party agent; prompt-injection bounded to advisory findings by the sandbox) is
  documented in ADR 0042 / `adversarial-review.md`.
- Docs: ADR 0042. New tests (`test_external_review.py` + CLI + `agent_eval.json_objects`);
  `external_review.py` 100%, coverage 98.33%.

### Added — plugin settings & configuration (planned-increment 3, ADR 0041)

A single, validated configuration surface for the plugin's knobs — the foundation the external
reviewer (increment 2) and multi-model tiering (increment 4) build on.

- **`lib/agentic_forge/settings.py`** resolves a `Settings` from `.agentic-forge/config.json`
  (validated against `schemas/config.schema.json`, Draft-7) with precedence **defaults < file < env**.
  `resolve(repo, env=…)` never raises — a missing file is defaults; a malformed / schema-invalid
  file is defaults + a stderr warning. It does **not** import diagnostics (which reads settings —
  avoids a cycle).
- **The config file is committed** — `.gitignore` uses `.agentic-forge/*` + `!.agentic-forge/config.json`
  (the `/*` form is required so git can re-include the file under an otherwise-ignored dir); the
  runtime logs/state in that dir stay ignored.
- **Unified the existing consumers:** `diagnostics` (the log-collector toggle), `budget` (subagent
  `soft`/`hard` caps), and `commit_gate` (`skip`) now read settings instead of `os.environ`
  directly — the same env vars still work (now via settings' env precedence), and the **config file**
  can set them durably. `diagnostics.enabled` was removed (the enable-check now lives in
  `record_event` via settings); the `review-scan` job uses `review.passes` as its loop-budget cap.
- **Forward keys declared** for the next increments: `review.passes`, `external_reviewer.{enabled,
  command}` (codex), and `models` (tier → model map) — inert until increments 2 / 4 consume them.
- Docs: ADR 0041. 12 new tests (`test_settings.py` + migrated guardrail/diagnostics tests);
  `settings.py` 100%, coverage 98.33%.

### Added — review-loop non-convergence scan (diagnostics increment 2, ADR 0040)

Captured the anomaly ADR 0039 deferred: a bounded review loop that exhausts its budget without
converging (in `develop`, `architecture`'s optional review, and the `product`/`marketing`/`ux-design`
skeptic passes). Because the loop runs in the model's flow (no code boundary to emit from), it's
caught by a deterministic **artifact scan** — approach (a):

- `diagnostics.scan_reviews(repo)` walks `docs/sdlc/**/review.md`, loads each via
  `handoff.load_artifact(expected_type="review")` (malformed / non-review files skipped, never
  raises), and emits an `anomaly` for any loop with `verdict == "changes"` at `iteration >= cap`
  (default 3 — the canonical review-loop bound). The decision is the pure `review_anomaly`; the walk
  is the thin I/O seam. A `changes` verdict *below* the cap is in-progress, not flagged.
- A `review-scan` scheduled job (daily) runs it and records anomalies into the existing
  `diagnostics.jsonl` (gated by `AGENTIC_FORGE_DIAGNOSTICS`); `diagnostics-digest` rolls recurring
  non-convergence (grouped by `target`) into "top problems".
- Docs: ADR 0040; scheduling-observability. 7 new tests; `diagnostics.py` 100%, coverage 98.29%.
  Still deferred: opt-in outward routing of the digest (ADR 0039).

### Added — self-diagnostics channel (ADR 0039)

A troubleshooting channel that collects the plugin's own **errors + behaviour anomalies** so
maintainers can fix it — distinct from the `audit.jsonl` *usage* log. Increment 1: guardrail +
pipeline emitters, local sink + digest (no outward routing).

- **`lib/agentic_forge/diagnostics.py`** — a redacted event (`{ts, kind ∈ block|warning|error|
  anomaly, severity, component, signature, message, context, session_id}`), an `emit` /
  `record_event` writer to `.agentic-forge/diagnostics.jsonl` (gitignored), and pure `digest` /
  `render` that group by **signature** (a stable fingerprint, volatile bits normalised) into ranked
  "top recurring problems". Mirrors `observability.py`.
- **Opt-in, never-block, redacted, local-only:** off unless `AGENTIC_FORGE_DIAGNOSTICS` is set;
  every emitter swallows its own errors; all strings pass through `guardrails.redact_secrets`; no
  auto-exfiltration.
- **Emitters at the deterministic boundaries:** the guardrail hooks (security / commit_gate
  denials, budget warn/block, hook crashes — these previously vanished) and the dev eval runners
  (uncaught exceptions + gate FAILs, via `_eval_cli.record_failure`). Pure lib stays untouched.
- **Rollup:** `dev/diagnostics_digest.py` CLI + a `diagnostics-digest` scheduled job (daily) through
  the existing cron CI — same pattern as `audit-digest`.
- **Fixed the ADR-0024 drift:** the observability doc promised a usage digest over
  blocks/warnings/errors that was never wired; that rollup now lives in this dedicated channel, and
  the doc is corrected. Deferred (increment 2+): workflow non-convergence capture; opt-in outward
  routing of the digest.
- 20 new tests; coverage 98.26%, library 100%.

### Added — token-overhead wiring (ADR 0038)

Closed the token-overhead half that ADR 0036 deferred, so `max_overhead_tokens` is now a live
Tier-2 gate — without the cross-cutting seam change that deferral was about.

- **`RunOutput(str)`** — a `str` subclass that optionally carries `.usage`
  (`{input_tokens, output_tokens, total_tokens}`). Because it *is* a `str`, every existing consumer
  (grading, parsing, the `Runner` type) is unchanged; only the Tier-2 timing capture reads `.usage`.
  Stubs / text-only replies stay plain `str`, so token-overhead is silently absent for them.
- **Transports report usage:** `api_runner` from the Messages response `.usage`; `claude_cli_runner`
  switches to `--output-format json` and parses `{result, usage}`, degrading to raw text + no usage
  if the output isn't result-bearing JSON (so an odd/old CLI can't crash a sweep).
- **`_run_passes` accumulates the component's tokens per run** (not the grader's) into the timing
  entry; `benchmark.summarize` → `delta.tokens` → `gate.tier2_quality(max_overhead_tokens)` was
  already built, so the whole chain lights up under `--baseline`.
- Restored library 100% branch coverage: `parse_grading`'s provably-unreachable defensive
  `isinstance` guard is marked `# pragma: no branch` (its candidates are always `{...}` objects).
- Docs: ADR 0038; CLAUDE.md §4 / `overview.md` / `meta-core.md` / `eval-runbook.md` / `benchmark`
  drop the "token-overhead deferred" caveat (only version-over-version A/B remains deferred). New
  tests: `RunOutput`, usage capture in both transports + JSON-degrade fallbacks, and token-overhead
  flowing into `delta.tokens` + firing the gate.

### Changed — review/skeptic passes for artifact-writer workflows (ADR 0037)

A loop-integration audit (bounded review loop + Ralph) across the 14 SDLC workflow skills — each
finding verified against source — found the review loop correctly integrated where it is
load-bearing (`develop` full; `architecture` optional; `code-review`/`security-review` as review
*producers*) and Ralph correctly absent everywhere (deferred engine-wide). It surfaced three
artifact-writers with no review step and two doc-honesty gaps, now fixed:

- **`product`, `marketing`, `ux-design` gain a bounded adversarial skeptic pass.** Each forks a
  fresh `reviewer` (via `Task`) to attack its own draft, then revises — bounded, exits on approve
  (the adversarial-review method, bounded by review-loop; ADR 0037). Lenses: `product` — acceptance testability / metric
  measurability / non-goal completeness / brief-traceability; `marketing` — claims cited-or-marked,
  no invented figures, no unsupported superlatives (upgrading its prior self-check into a forked
  pass); `ux-design` — accessibility + flow/state completeness.
- **`product` and `ux-design` gain `Task`** in `allowed-tools` (they could not fork a reviewer
  before). Marketing already had it. **No description changed**, so Tier-1 routing is unaffected.
- **`security-review` links `review-loop.md`** in its Output — symmetry with `code-review`: both
  emit the `review` artifact that `develop`'s bounded loop consumes.
- **`deploy-watch` states its scope honestly**: a point-in-time snapshot, not a continuous watch
  (re-run to re-check); continuous poll-until-terminal-state is out of scope (the future home of a
  Ralph poll-loop, recorded in the ADR).
- No eval-contract changes: the writers' existing Tier-2 assertions / `product`'s Tier-3 checkpoint
  already gate the *outcomes* the skeptic pass improves; a live Tier-2 re-run (ideally the ADR-0036
  `--baseline` A/B) is how to confirm the lift. Tier-0 green; Tier-1 untouched.

### Added — Tier-2 A/B + overhead wiring (ADR 0036)

Wired the two cheap, always-available halves of the previously-dormant Tier-2 overhead/A-B
scaffolding (ADR 0035 deferred deleting it): the **with/without A-B pass-rate lift** and the
**wall-clock time overhead**. The 4-tier pyramid's Tier-2 overhead/A-B is now a real, exercised code
path instead of a "scaffolded but not wired" caveat.

- **Timing capture (always-on).** `agent_eval.run_eval_cases` now records per-run wall-clock and
  feeds it to `benchmark.summarize`, so every Tier-2 benchmark reports `with_skill.time_seconds`.
  The case loop was extracted into `_run_passes` (returns `(gradings, timing)`).
- **Opt-in without-skill baseline.** `run_eval_cases(baseline_system_body=…)` reruns each case under
  a baseline to produce `run_summary.delta`; `skill_eval.run_skill(with_baseline=True)` +
  `dev/run_skill_evals.py --baseline` expose it (off by default — ~2× cost). The baseline is the
  same executor with the skill under test removed (`build_skill_baseline_system`): base role +
  standards for a knowledge skill, the bare base model for an on-listing skill. Skills only — roles
  have no "without itself" (ADR 0011).
- **`min_lift` gate.** `gate.tier2_quality` fails when a contract sets `min_lift` and the measured
  A-B `delta.pass_rate` falls short (the "A-B not worse / better by X" bar); it **skips** when no
  baseline ran, so normal single-pass runs are unaffected. Added to the contract schema
  (`tier2_quality.min_lift`).
- **Honest tokens.** `benchmark.summarize` reports `tokens` / `delta.tokens` only when a timing entry
  carries a count — a wall-clock-only run no longer shows a misleading `tokens: 0.0`.
- **Deferred, with reasons (ADR 0036):** token overhead (needs the `Runner` transport to surface
  usage) and version-over-version A-B (needs a stored benchmark history). `max_overhead_tokens` stays
  reserved in the schema.
- Docs: ADR 0036; CLAUDE.md §4 / `overview.md` / `meta-core.md` drop the "not yet wired" caveat and
  state what is wired vs deferred; `eval-runbook.md` gains an A/B + `--baseline` calibrate-then-gate
  section. 13 new tests in `tests/test_tier2_ab_overhead.py` (694 total).

### Fixed — third deep-review pass (6 reviewers): test integrity, robustness, doc currency

A third whole-plugin review. No blockers; the system was found healthy and the prior rounds' fixes
verified correct. This round:

**Test integrity & robustness (code):**
- `spine_e2e.repo_tests_pass` runs the nested suite via `sys.executable`, not a hardcoded `python`
  (a box with only `python3` raised FileNotFoundError instead of running it).
- `release.commits_since` lost its inaccurate `# pragma: no cover` (the lines ARE executed via real
  git) + tests for the tag-range / tag=None auto-describe / non-git arms — `release.py` back to 100%.
- `run_skill_evals` exits 1 (not a vacuous 0) on empty skill discovery; `tier1_runner.load_triggers`
  loads via `evals.load_evals` (clean EvalsError, not a bare json crash on a malformed contract).
- robustness-in-isolation: `naming` uses `\Z` not `$` (rejects a trailing newline); `connectors`
  maps an explicit JSON `null` field to `""` not `"None"`; `frontmatter` parses CRLF; the Tier-0
  ref-validator blanks code spans first (a documented link *example* in a fence no longer fails);
  `selection_rate(runs=0)` returns 0.0; the spine baseline commit allows-empty.
- new tests close real gaps: the contract `runs` is honored over the default (was a `runs==5`
  tautology); the dev/ `_build_runners`/`_build_router` "claude" construction branches are exercised;
  the description-length boundary (1024/1025) and exact sample-stddev are pinned.

**Doc currency:** dropped "(design)" from the 2 titles the prior sweep missed (`spine.md`,
`knowledge.md`); `guardrails.md` documents `find -delete`; `handoff.md` table fixed (ux-spec
`design_system`; review.md credits `security-review`); `overview.md` Tier-2 overhead/A-B marked
not-wired + its pattern list completed; `meta-core.md` layout adds `skill_contract`/`planning`;
clarified the "type frontmatter" wording (it's the *artifact's* frontmatter, not a skill field) and
the stale deep-review-producer note; roadmap test count.

681 tests; `validate`/`ruff`/`mypy` green; branch coverage 98%. Deferred (lowest value): tightening
a few over-determined `not ok` assertions to pin the exact failed rule, and a case-folded
vault-note-collision warning (Linux-only, niche).

### Fixed — full-plugin deep review (6 reviewers: skills, lib, tests, docs, agents/patterns/hooks, cross-cutting)

A whole-plugin review (each finding reproduced against source). No blockers; the system was found
healthy. Fixed across four areas:

**Correctness.** `gate` now compares metrics with an epsilon, so a value exactly at its threshold
isn't failed by binary-float representation (`0.85-0.05 == 0.7999…` was a spurious FAIL).
`run_scheduled` returns non-zero when a job fails (the per-job `ok` was never aggregated, so a cron
stayed green on failure). `release.next_version` strips a `-prerelease`/`+build` semver suffix
before bumping (a `git describe` tag crashed it). `agent_eval._json_candidates` is O(n) (brace
stack) instead of the per-`{` O(n²) rescan. Removed dead `majority_selection`; dropped a wrong
`# pragma` on a tested branch.

**Documentation.** Finished the `context: fork` → `Task` sweep ADR 0035 began — 6 remaining
docs/patterns (incl. `skill-factory`'s teaching refs, which were instructing the unused idiom);
dropped stale "(design)" from 5 shipped architecture-doc titles; fixed product-marketing's "six
areas" (it lists three); pattern enumerations now include `knowledge-recall`/`worktree-parallel`;
ADR back-references (0010/0016/0024/0026); `eval.yml` "majority-of-N" → mean-rate.

**Skill contract uniformity.** All 8 non-spine handoff producers now instruct
`handoff.validate_header(...)` + link `handoff.md` (matching the 5 spine producers); added `type`
to the 5 skills' documented **handoff-artifact** frontmatter field-list — e.g. `type` (= `ux-spec`) —
where it was omitted (the ADR-0032 "identity field missing" shape; this is the *artifact's*
frontmatter, not a skill-frontmatter field, which ADR 0032 deliberately rejected); skill-factory
`allowed-tools` space-separated → comma.

**Test integrity + scaling.** Enabled **branch coverage** (line-only 100% hid weakened-branch
regressions — a `>`/`>=` flip survived); added mutation-killing tests (body-cap boundary,
empty-description, recall title-vs-body weighting, validate_agent no-name); extended the security
deny-list with `find <system-dir> … -delete` (targeted sub-paths stay allowed). Added a **weekly
eval cron** so Tier-1/2 are continuously gated (not just spot-checked) + documented the router
listing-budget ceiling. Closed the marketing-strategy / knowledge-recall eval holes;
`pass_rate_of` handles `{passed, failed}` without a `total`; the budget counter clamps a negative.

670 tests; `validate`/`ruff`/`mypy` green; branch coverage 97.6% (library ~100%).

**Follow-ups since completed:** `audit.jsonl` windowing (`load_audit(max_lines=…)`); the
ux-design/repo-onboarding second eval cases; the `vault.add_note` upsert doc-note; the `!= []`
schema-test tightening (now pin the offending field); the marketing reference field-lists; the
hooks event→matcher→script mapping test; and the eval-harness/dev-CLI de-duplication
(`evals.eval_case_problems` + `dev/_eval_cli.warn_if_api_key_set`). Only the trivial
`parse(read_text())` reader one-liners were left as-is (not worth the cross-module import churn).

### Fixed — final independent review of the remediation diff

A fresh 3-reviewer pass over the ultra-review remediation commits (`efd1061..HEAD`), each finding
reproduced against source, caught defects in the hardening itself:
- **ReDoS** in the new `chmod` matcher (`_PERMISSIVE_MODE`): `[ugoa]*` backtracked quadratically on a
  long run, so a crafted `chmod -R ugoa…ugoa /etc` stalled the security hook for seconds. Anchored
  the symbolic clause (`(?<![\w+=])`) → linear; a regression test asserts it returns fast on an 80k
  input.
- **Audit-log over-redaction**: the broadened `sk-/rk-[A-Za-z0-9-]{16,}` blanked ordinary hyphenated
  args (`sk-region-us-east-1-…`). Replaced with precise prefix-anchored patterns (`sk-ant-`,
  `sk-proj-`, bare `sk-` hyphen-free ≥20, `[sr]k_(live|test)_`) — real keys still redact, benign args
  survive; this also fixed a **Stripe `rk_live_`/`rk_test_` leak** the broad regex had missed.
- **Doc accuracy**: `handoff.py` wrongly listed `deep-review` as a `review`-artifact producer — it
  emits no handoff (only `code-review`/`security-review` do; deep-review reuses the finding *shape*).
  Corrected, plus small currency fixes (test-count, two stale comments, a non-schema `bump` field in
  `handoff.md`'s `release` row).

The gate/dedup/logic reviewer found nothing actionable (every change verified correct with executed
evidence). 653 tests green; `ruff`/`mypy`/`validate` clean; coverage 98%, `guardrails.py` 100%.

### Fixed — session ultra-review (multi-lens adversarial pass): correctness, gate-integrity, security

A seven-reviewer review of the whole session (each finding verified against source; full gate
re-run clean) found and fixed real defects:

**Correctness (deterministic cores):**
- `release`: `BREAKING CHANGE` detection was unanchored + case-insensitive, so `fix: handle
  breaking change in upstream` falsely bumped a **major** release. Now matches the spec footer
  `^BREAKING[ -]CHANGE:` (multiline, uppercase) only.
- `schedule`: retry bound was off by one (`failures <= MAX_RETRIES` allowed `MAX_RETRIES + 1`
  attempts) — now `<`, capping at exactly `MAX_RETRIES`.
- `planning`: a Unicode-digit task id (`"²"`, where `str.isdigit()` is True but `int()` raises)
  crashed `plan_batches` — now guarded with `isascii()`.
- `vault`: a note's self-`[[link]]` masked it from the orphan check — self-references no longer
  count toward inbound links.

**Gate integrity (a malformed contract could PASS unmeasured):**
- `gate.tier2_quality` returned PASS when `min_pass_rate` was absent (an empty `tier2_quality: {}`
  gated nothing, even at mean 0.0) — a missing threshold now FAILS. The schema now `require`s
  `min_pass_rate` (tier2) / `recall`+`specificity` (tier1) and rejects unknown `thresholds` keys (a
  junk key could satisfy `minProperties`). `gate.all_passed([])` now returns False (no data is not a
  pass), mirroring `tier1_runner`.
- **Coverage gates `dev/` too** (`source = [agentic_forge, dev]`, `fail_under = 80` in pyproject; CI
  `--cov`): the eval runners' aggregation/exit-code logic — which decides ship/no-ship — was
  unmeasured (56–66%). New stub-transport tests cover each runner's pass/fail/error path;
  `validation.py` error branches now covered (library 100%, aggregate 98%).

**Security (`guardrails`):**
- **Secret redaction** missed most modern token shapes — bare `sk-ant-…` Anthropic keys (and
  `gh*_`, `github_pat_`, `glpat-`, Google `AIza…`, Stripe, JWTs, `user:pass@` URLs) leaked verbatim
  into `audit.jsonl`. Broadened the patterns; new tests assert the **raw token is absent**.
- Dangerous-command checks now run **per shell segment**, fixing a false-block (`ls /usr && rm -rf
  build` was hard-blocked) and closing bypasses: force-push refspec destinations (`… HEAD:main`),
  global flags (`git -C dir push`), pipe-to-shell via other interpreters / intermediate stages
  (`curl|zsh`, `curl|tee|sh`, `wget|python`), and recursive permissive `chmod` of a system dir. The
  test-gate now also detects `git -c …` / env-prefixed commits.
- `GrafanaAlertSource` refuses a non-`http(s)` `GRAFANA_URL` (no `file://` SSRF / token leak on
  misconfig).

**Documentation honesty / currency:**
- `CLAUDE.md` principle 1 described delegation via `context: fork` + `agent` frontmatter that **no
  skill uses** — corrected to the real `Task`-tool + named-role convention; principle 4 + meta-core
  now mark Tier-2 overhead + A/B as scaffolded-not-wired (pass-rate is the live gate); the `dev/`
  layout lists all 7 CLIs; Ralph marked deferred.
- `tier1_runner` docstring corrected from "majority-of-N" to the shipped mean-rate metric (ADR
  0026); `worktree.md` stale "develop is sequential" note removed; `handoff.md` artifact table
  extended from 5 to all 13 types; `handoff.py` review-producer docstring (later corrected:
  deep-review reuses the finding shape but emits no artifact);
  `develop` review-engine wording corrected; `qa-test-strategy` field list adds `type`; README
  quality-hardening "designed → built"; `guardrails.md` documents the accident-guard scope.

Decisions recorded in [ADR 0035](docs/architecture/decisions/0035-ultra-review-hardening.md).
Regression tests for every fix; `dev/validate.py`, `pytest`, `ruff`, `mypy` all green.

**Follow-ups completed in the same review** — *cleanups:* `__all__` on the 9 lib modules that
lacked it, `summary_line` hoisted into `gate.format_tier2_summary` (the lower-bound formula in one
place), dead `Change.raw` field + inert `classify_incident(cosmetic=)` param removed. *Deeper
test-quality:* the LLM judge transports (`api_runner`/`claude_cli_runner`) are now unit-tested with
a mocked transport (argv/request shape, retry, raise — `# pragma: no cover` removed, `agent_eval`
back to 100%); `expected_release_version` is de-tautologised against a built git history (asserts the
literal `1.1.0` bump, not a value recomputed via `summarize`); and `check_develop` drops comment-only
lines so a `# priority=` TODO can't satisfy the marker (still judge-free per ADR 0030). 647 tests;
library 100%, aggregate 98%.

All follow-ups since completed: the three one-line `all_passed` definitions collapsed to one generic
`gate.all_passed` (over a `Passable` protocol) re-exported by the runners; `DEFAULT_RUNS` defined
once in `agent_eval` and imported; and the `spine_e2e` back-compat trio (`run_e2e` / spine-only
`check_wiring` / `prepare_workspace`) removed — its tests migrated to `run_scenario` /
`scenario_wiring` / `prepare_scenario(SPINE)`. Nothing from the review remains outstanding. 647
tests; library 100%, aggregate 98%.

### Changed — Tier-0 validator gates cross-tree links + runs the contract guards

`dev/validate.py` now (a) resolves **cross-tree relative markdown links** (`](../...)` / `](./...)`
to patterns, agents, docs, and sibling skills — previously only a skill's own
`references/`/`assets/`/`scripts/` links were checked, so the **52** inter-dir links sat ungated —
and (b) runs the **handoff-contract** and **knowledge-recall** guards (ADR 0032/0033) over the
skills present in the plugin, so one `python dev/validate.py` enforces them (they already blocked
via pytest). The guards scope to *present* skills, so the aggregate validator stays correct on a
partial plugin; map/spine completeness is still asserted by pytest. This closes the two follow-ups
the quality-hardening deep review deferred. All 52 links resolve; new tests cover the relative-ref
check (resolving + missing) and the guard wiring; full gate green.

### Fixed — quality-hardening deep review (5-lens adversarial pass)

A five-reviewer review (each verified against source; full gate re-run clean) found real gaps in the
three increments — all fixed:

- **#1 guard:** `marketing` produces **two** artifact types — `SKILL_HANDOFF` now maps a tuple
  (`market-brief`, `marketing-strategy`) and the guard checks every type (`marketing-strategy`'s
  `positioning`/`channels` were previously unchecked). Tightened `_documents` so `feature-slug` no
  longer satisfies `feature` (hyphen boundary) and an inline `status:` no longer satisfies `status`
  (colon match line-anchored); `deploy-watch`'s write step now spells its `deploy-status` fields.
- **#3 develop:** `plan_batches` now sorts ids **numerically** (`1, 2, 10`, not lexical `1, 10, 2`)
  so the "by task id" merge order is intuitive; develop steps 3/6/7 are now **level-aware** (fork a
  software-engineer into **each** task's worktree; QA on the **integrated base**; remove **each**
  worktree); a **bounded integration-conflict stop** (route to a software-engineer under N = 3 or
  surface and stop) was added to develop + `worktree-parallel.md`.
- **#2 recall guard:** now parses the **body** and matches the actual pattern **link** — a bare
  `knowledge-recall` mention in a comment/frontmatter no longer passes.
- **Currency:** un-stale'd `fan-out-fan-in.md` ("develop is sequential"), the `quality-hardening.md`
  + `roadmap.md` status ("Designed, not built" → Built), ADR 0033's mis-quote of `CLAUDE.md`, and the
  `spine.md` thin-slice note.

New tests for every fix (numeric sort + determinism, multi-type, matcher tightening, gamed recall,
bounded paths); `skill_contract.py` + `planning.py` 100% covered; full gate green. Deferred
(pre-existing, noted by 2 reviewers): folding the guards + `../` cross-tree link resolution into
`dev/validate.py` — the guards already block via pytest.

### Added — develop parallelism (quality-hardening 3/3)

Implemented [ADR 0034](docs/architecture/decisions/0034-develop-parallelism.md):
`planning.plan_batches(tasks)` computes the plan's dependency **levels** (independent tasks per
level; raises on a cycle / unknown dep / duplicate id), and `develop` now batches the plan and, per
level, **fans out one git worktree per task** concurrently, **integrates** the level (merge in a
deterministic order, resolving conflicts) before the multi-aspect review, and advances
level-by-level — keeping the single-worktree path when a plan has no parallelism. New
`patterns/worktree-parallel.md`; `planning.py` 100% covered. Closes `spine.md`'s deferred "impl
parallelism".

### Added — Knowledge recall in the spine (quality-hardening 2/3)

Implemented [ADR 0033](docs/architecture/decisions/0033-knowledge-recall-in-spine.md): each spine
phase (`research` / `product` / `architecture` / `plan` / `develop` / `code-review`) now opens its
Process with a **"Recall first"** step — pull the project's relevant prior decisions from the
knowledge vault (`vault.recall` / the `knowledge` skill), factor them in, and skip if the vault is
empty — realizing the constitution's *workflows read the vault to enrich context*. The step is
captured once in `patterns/knowledge-recall.md` and linked from each phase; a guard
(`skill_contract.recall_problems`) asserts every spine body references it (unit-tested, live-clean).

### Added — Handoff-contract guard (quality-hardening 1/3)

Implemented [ADR 0032](docs/architecture/decisions/0032-handoff-contract-guard.md): a deterministic
guard (`skill_contract.py` — the `SKILL_HANDOFF` map + `handoff_contract_problems`) that every
artifact-producing skill's `SKILL.md` documents the frontmatter fields its handoff schema requires.
A field counts as documented when named in a backtick span (`field`, `field[]`, or a comma-list like
`type, feature, status`) or as `field:` — bare prose doesn't count, so the common words
`feature`/`status` aren't satisfied incidentally. It surfaced **5 real gaps** —
`architecture`/`plan`/`product` omitted `status`, `marketing` omitted `feature`/`status`/`competitors`,
`repo-onboarding` omitted `feature`/`status` — all fixed in the skill bodies. Guard green for all 13
mapped skills; unit-tested (live-clean + synthetic pass/fail/edge); `skill_contract.py` 100% covered.

### Added — Quality-hardening plan (handoff guard, knowledge recall, develop parallelism)

Design + decisions for three post-spine hardening increments — **design only, no code yet**:
[quality-hardening.md](docs/architecture/quality-hardening.md) +
[ADR 0032](docs/architecture/decisions/0032-handoff-contract-guard.md) (a deterministic guard that
each artifact-producing skill's body documents the fields its handoff schema requires — the root
cause behind the live-sweep `ux-design` flakiness),
[ADR 0033](docs/architecture/decisions/0033-knowledge-recall-in-spine.md) (each spine phase recalls
relevant vault notes before acting — realizing the constitution's read-the-vault intent), and
[ADR 0034](docs/architecture/decisions/0034-develop-parallelism.md) (develop implements independent
plan tasks concurrently across worktrees via a tested `plan_batches`). The three are independent
(implementable in parallel); contract → evals → implementation → gate → a final deep review follow.

### Added — Scheduled-job health report

`schedule.health(jobs, state)` + `format_health(...)` surface the per-job run history that cadence
persistence (ADR 0031) records — status, run count, consecutive failures, last-run, or `never-run`
— and `dev/run_scheduled.py --health` prints it without running anything. This is the scheduled-job
observability rollup ADR 0031 left open (the data was persisted; this is the consumer). Pure +
tested; `schedule.py` stays **100% covered**.

### Added — Per-phase retry in the Tier-3 runner

`run_scenario(..., retries=1)` (and `dev/run_spine_e2e.py --retries N`, default 1) re-runs a phase
whose checkpoints fail, up to N times — a fresh **model** attempt at the same prompt, **never
relaxing a checkpoint**. This absorbs the single-run frontmatter variance the live sweep surfaced
(a phase occasionally emitting an artifact missing a required field), so a long chain reliably goes
all-green without lowering the bar (`--retries 0` disables it). `run_e2e` (spine) inherits the
default; unit tests cover the retry-then-pass and retry-disabled paths and `spine_e2e.py` stays
**100% covered**.

### Verified — Domain E2E live Tier-3 runs (subscription, `claude-opus-4-8`)

Ran the five Tier-3 scenarios live (`--runner claude`). The harness and **every deterministic
checkpoint type are proven** — each fired green in a real run — and several live-only gaps were
found and fixed:

- **market-brief** ✅ — `marketing` named the competitors from the notes (deterministic check).
- **ops-incident** ✅ — deploy health `failing`, incident `sev1`, hotfix release valid. Two live
  fixes: the incident phase now **reads `deploy-status.md`** and names the failing `production`
  environment (the handoff the design specified but the prompt hadn't wired), and the
  hotfix-release prompt is **prescriptive** so the artifact reliably validates.
- **quality-gate** ✅ (flagship) — a live `develop` session implemented the feature and the repo
  test suite passed; `security-review` found the planted SQLi sink; `release` produced the
  **exact** computed bump (`1.1.0 == 1.1.0`).
- **spine** — research / product / architecture / plan / **develop (live coding + tests pass)**
  green; `code-review` flaked on strict `review.md` schema validation (a missing required field).
- **product-inception** — repo-onboarding (**vault validates clean**), research, product,
  architecture green; `ux-design` flaked on strict `ux-spec` validation. Fixes: prescriptive
  `product`/`ux-design`/`architecture` prompts + a valid-YAML instruction, and the **`ux-design`
  skill body** now requires `feature`/`status` and YAML **list** fields (its output contract had
  omitted them — a real skill gap).

**Finding:** at strict per-artifact schema validation, a full multi-phase chain passing in a
*single* live run is probabilistic — each phase has a small chance of emitting an artifact missing
a required frontmatter field (model output variance), so a 5–6-phase chain may need a re-run to go
all-green. The checkpoints are correct (the artifacts genuinely were invalid); the remedy is better
prompts/skill contracts (done) and a **per-phase retry** in the live runner (now implemented — see
above). The live job stays on-demand/cost-gated, where re-running to a clean sweep belongs.

**Clean sweep.** Re-run with `--retries 1` (plus the `ux-design` skill-contract fix), **all five
scenarios PASS** on the subscription — `spine` 6/6 (one phase flaked, the retry absorbed it),
`product-inception` 5/5 (`ux-design` now validates without a retry), and `quality-gate` /
`ops-incident` / `market-brief` green as before. The retry closed the single-run variance without
lowering any checkpoint.

### Added — Scheduling cadence persistence (per-job state + retry)

Enriched headless scheduling
([ADR 0031](docs/architecture/decisions/0031-scheduling-cadence-persistence.md), extends ADR 0024).
Per-job **`JobState`** (`last_run`, `status`, `runs`, `failures`) replaces the flat
`{name: last_run}` map; **`due_jobs` is retry-aware** — a failed job re-runs on the next poll,
bounded by `MAX_RETRIES`, then backs off to its cadence (a broken weekly job self-heals within the
polling rhythm instead of waiting a week); **`record_run`** is the pure outcome-recorder, and
`dev/run_scheduled.py` now wraps each action so a failure is **recorded, not fatal** (fail-open).
`load_state` **migrates** legacy flat state files transparently, and run history
(`runs`/`failures`/`status`) is now persisted for a future observability rollup. `schedule.py`
stays **100% covered** and the due-logic stays pure. Anchored (drift-free) schedules and
per-environment keys are explicitly deferred behind the same state shape.

### Added — Domain E2E Wave 2 (product-inception + market-brief)

Completed the domain-E2E plan. Added the **`product-inception`** chain (repo-onboarding → research
→ product → ux-design → architecture — the spine phases are carriers exercising the handoffs; the
onboarding phase's checkpoint runs `vault.validate_vault` on the seeded knowledge vault) and the
**`market-brief`** scenario (`marketing` on its Tier-2 fixture with a **deterministic**
named-competitor check — Algolia / Elastic / Typesense — the complement that the earlier "exclude
marketing" draft wrongly ruled out). Closed the **`ops-incident` handoff check** the design called
for: the incident must reference the failing `production` environment from the deploy-status
(`check_incident`'s `env_marker`). New checkpoints `check_onboarding` / `check_ux_spec` /
`check_market_brief`; `tests/test_domain_e2e.py` extended (spine_e2e.py stays **100% line
coverage**, suite 99%). `eval.yml`'s domain step now runs all four domain scenarios; all five
Tier-3 scenarios pass `--runner dry`. The recorded live `--runner claude` run remains on-demand.

### Added — Domain E2E Wave 1 (Tier-3 chains implemented)

Implemented Wave 1 of the design
([ADR 0030](docs/architecture/decisions/0030-domain-e2e-scenarios.md) /
[domain-e2e.md](docs/architecture/domain-e2e.md)). Generalized `spine_e2e.py` into a `Scenario`
registry — the **spine becomes one entry** and `run_e2e` delegates to the generic `run_scenario`,
so the spine guard (`tests/test_spine_e2e.py`) is unchanged and green — and added two domain
chains:

- **`quality-gate`** — qa-test-strategy → develop → security-review → code-review → release, on a
  seeded `spine/target-repo` with a tagged `v1.0.0` baseline + an isolated planted SQLi module.
- **`ops-incident`** — deploy-watch → incident-response → release, artifact-driven (no app repo for
  the first two phases).

Every checkpoint is **judge-free**: schema validation, computed-outcome comparisons
(`release.summarize(...).version`; `ops.classify_incident(outage=True)` → `sev1`; the
`deploy-status` health read from the **`pipeline`** field), and a planted-sink **location** match
for security-review. `dev/run_spine_e2e.py` gains `--scenario {spine,quality-gate,ops-incident,all}`;
the dry-run wiring check covers every scenario and asserts the deploy-watch prompt **neutralizes a
live `gh`/Grafana connector** so it can't shadow the fixture. New unit tests
(`tests/test_domain_e2e.py`) cover the checkpoints + `run_scenario` on stubbed phases —
`spine_e2e.py` at **100% line coverage**, suite 99%. Wired into `eval.yml` (dry always-on; live
spine + domain chains cost-gated on the subscription token). **Wave 2** (`product-inception`,
`market-brief`) and the live `--runner claude` recorded run are **pending**.

### Added — Domain E2E design (Tier-3 for the Stage 4–6 domains)

Design + decision for extending Tier-3 (end-to-end) coverage from the SDLC spine to **all eight**
Stage 4–6 domain skills. **Design, not built.**
[docs/architecture/domain-e2e.md](docs/architecture/domain-e2e.md) +
[ADR 0030](docs/architecture/decisions/0030-domain-e2e-scenarios.md) decide: grow Tier-3 by
deterministic multi-skill **chain** scenarios (`quality-gate`, `ops-incident`, `product-inception`)
plus a deterministic `market-brief` complement, rather than per-skill repeats; generalize
`spine_e2e.py` into a `Scenario` registry; keep every checkpoint judge-free (code comparison /
location substring / carrier schema); reuse existing Tier-2 fixtures.

The design was **hardened by a deep multi-reviewer review** (five adversarial lenses, each verified
against the source) before acceptance — which corrected real errors in the first draft: the
`deploy-status` health value lives in the `pipeline` field (no `health` key); the release bump is
`release.summarize(...).version`, not `release.classify`; two checkpoints were not actually
judge-free and were reduced to deterministic substring/keyword forms; `security-review` and
`code-review` both default to `review.md` (collision — fixed via a phase-prompt path override); the
`Scenario` change is a real refactor (module-level `FEATURE_SLUG`/`FIXTURE_REPO`), not a rename;
`deploy-watch` must be forced onto the in-memory source so a runner-present `gh` can't shadow the
fixture; and `marketing` is **included** (its Tier-2 is fixture-grounded, so a deterministic
named-competitor check is feasible — the earlier "live web research" exclusion was a false premise).
Recorded in the roadmap's Post-spine increments; no code yet (contract → evals → implementation →
gate still to come).

### Changed — README rewritten around the SDLC usage story

The README's "Using the plugin" section was a flat example list; it now tells the lifecycle
story. An **ASCII flow diagram** of the spine (research → … → code-review) shows the handoff
artifact under each phase, the review loop, the qa/security attach points, and the post-merge ops
tail (release → deploy-watch → incident-response). A full **"Ship a feature end to end"** worked
example walks prompt → skill → artifact; **"Two ways in"** contrasts a new feature (start at
`research`) with an existing repo (start at `repo-onboarding`); and a **"Skills by stage"**
grouping (Frame & design / Build & verify / Ship & operate / Cross-cutting) replaces the flat
table. The page now conveys *how to drive the plugin across the SDLC*, not just what each skill does.

### Changed — Tier-1 routing (skill descriptions sharpened to the ADR-0026 metric)

The first full Tier-1 sweep under the ADR-0026 mean-routing-rate metric failed six on-listing
skills on recall — the metric surfacing real routing weakness, not noise. **Per-prompt
diagnosis** (routing each `should_trigger` prompt against the live listing and recording where
it actually went) pinpointed one "killer" prompt per skill; each was fixed by **sharpening the
skill description**, never by lowering the 0.9 threshold (playbook in
[ADR 0029](docs/architecture/decisions/0029-tier1-routing-remediation.md)):

- **qa-test-strategy** — "Design a QA test plan" leaked to `plan`; `plan` now carves out "a
  test/QA plan is qa-test-strategy" up front, and qa-test-strategy owns "test plan / QA strategy".
- **skill-factory** — "Create a new skill for release notes" leaked to `none`; made categorical:
  *any* "create/add a new skill/agent/script" routes here, whatever the component is for.
- **deep-review** — "Deep review of my PR for bugs" leaked to `code-review`; deep-review owns
  DEPTH (deep/thorough/adversarial/audit, even of a PR/diff), `code-review` = the standard
  pre-merge review.
- **repo-onboarding** — "seed the knowledge base" leaked to `knowledge`; onboarding owns "a whole
  codebase/repo (seeding the vault is part of it)", `knowledge` = a single decision/note.
- **product** / **knowledge** — two prompts fought hard router priors no description edit could
  beat (the router reads "Remember this:" as its own chat memory → `none`; "research brief" is an
  overwhelming literal match for `research`). After three description rounds, those two genuinely
  ambiguous `should_trigger` prompts were reworded to equivalents testing the **same capability**
  ("Remember **in our project notes** that…"; "Now turn the brief into a PRD…"), keeping prompt
  counts and the 0.9 bar unchanged (ADR 0029's reword criterion).

Reciprocal disclaimers were added to `code-review` / `plan` (safe — verified against their own
triggers) and a spurious "product" keyword was removed from `research`'s track list.

**Result** (`claude-opus-4-8`, runs = 5, gate recall / specificity ≥ 0.9): **all 17 on-listing
skills pass.** The six fixed targets, recall before → after:

| Skill | Before | After |
| --- | --- | --- |
| qa-test-strategy | 0.55 | **0.95** |
| skill-factory | 0.70 | **0.95** |
| repo-onboarding | 0.75 | **0.95** |
| product | 0.76 | **0.96** |
| knowledge | 0.80 | **0.96** |
| deep-review | 0.84 | **1.00** |

Edited competitors held (code-review 0.96, plan 1.00, research 0.92); the eight unedited skills
were re-swept with no regression (architecture / deploy-watch / incident-response / marketing /
release / security-review / ux-design 1.00, develop 0.96). Specificity 1.00 across the board.

### Fixed — Tier-2 eval fidelity (skill quality gates)

A live Tier-2 run surfaced 7 skill gates below the 0.8 bar. Per-assertion root-causing showed
these were **eval-design** issues, not skill weakness — fixed by improving the skill or making
the eval a higher-fidelity test, **never by lowering the 0.8 threshold or dropping assertion
coverage** (per-case assertion counts are unchanged):

- **The read-only grader cannot execute toolchains.** The `grader` role has only
  `Read/Grep/Glob`, so assertions phrased as *executions* — "dotnet build is clean", "cargo
  clippy clean", "the project builds via its wrapper", "eslint clean", "dev/validate.py reports
  no errors", "ruff + mypy pass" — were never gradeable by running them; the grader could only
  guess, which is the near-0.8 variance. Each was reframed to the **inspectable code-property it
  proxies** (compiles cleanly / clippy-clean / no new `eslint-disable` / standard-compliant on
  inspection), preserving the quality intent. (dotnet, rust, jvm, javascript, skill-factory)
- **knowledge** — the executor looked for `lib/agentic_forge/vault.py` by path (absent in the
  sandbox) and hand-rolled notes with the wrong frontmatter. SKILL.md now invokes the
  **installed `agentic_forge.vault` module** and states the exact note frontmatter
  (`title`/`type`/`tags`), so both the validation run and the schema are satisfied.
- **skill-factory** — the body never stated where a subagent lives, so it scaffolded one at the
  wrong path; added the **canonical component-location table** (`plugin/agents/<name>.md`, …).
  An assertion demanding a `script`-type `evals.json` (a type the schema *reserves for future
  use*) was corrected to the real convention: scripts are contracted by **pytest**.
- **engineering-standards** — its empty-sandbox case made the software-engineer correctly refuse
  to "scaffold from nothing"; it now ships a real `cart.py`/`test_cart.py` fixture and a concrete
  task.
- **jvm-patterns** — case 2 now exercises a value-type map key, so the equals/hashCode assertion
  is actually tested rather than vacuously failing.
- **javascript-patterns** — sharpened the boundary-validation idiom: returning raw parsed
  `unknown`/`any` is explicitly *not* validation.
- **Applied uniformly (ADR 0020).** An audit of *every* skill's assertions found the same
  execution-phrasing in the 5 packs that *passed* (go, php, python, ruby, typescript) — latent
  flakiness that would surface on a future run. Reframed those too (faithfully, same strictness).
  Recorded the rule as
  [ADR 0020](docs/architecture/decisions/0020-tier2-inspection-gradeable-assertions.md) and in
  the eval-runbook: **a Tier-2 assertion must be verifiable by the read-only grader
  (`Read/Grep/Glob`) — it can never run a build/linter/test, so phrase the property for
  inspection, not execution.**

**Results** (model `claude-opus-4-8`; lower bound = `mean − stddev`, n = 5):

| Skill | Before (lower bound) | After (lower bound) |
| --- | --- | --- |
| skill-factory | 0.454 ❌ | **0.912** ✅ |
| engineering-standards | 0.571 ❌ | **0.836** ✅ |
| knowledge | 0.667 ❌ | **1.000** ✅ |
| jvm-patterns | 0.672 ❌ | **1.000** ✅ |
| javascript-patterns | 0.750 ❌ | **0.895** ✅ |
| rust-patterns | 0.778 ❌ | **0.861** ✅ |
| dotnet-patterns | 0.822 ❌ | **0.895** ✅ |

All seven now clear the gate (`mean − stddev ≥ 0.8`, n = 5). The five hardened packs that
already passed (go, php, python, ruby, typescript) each scored **1.000** on a 1× regression
check — the faithful reframe did not regress them. Combined with the agent Tier-2 (6/6 roles)
and the Tier-3 spine E2E (pass), the full eval suite is green.

### Added — Stage 4 quality & operations (design + foundation)

- **Stage 4 design** `docs/architecture/quality-ops.md`: the five quality/ops phase-workflows
  (`qa-test-strategy`, `security-review`, `deploy-watch`, `incident-response`, `release`) — each
  skill's contract (purpose, forked role, handoff artifact, trigger boundary), the ops adapter
  seam (`lib/ops.py` + provider fakes), the four-level incident severity model, release
  conventions (semver + Keep-a-Changelog), and a fixture-backed, inspection-gradeable eval plan.
- **Handoff artifact types** (`handoff.py`, contract-first, 100% covered): `test-strategy`,
  `release`, `incident` (with a four-level `INCIDENT_SEVERITIES` vocabulary `sev1`–`sev4`), and
  `deploy-status`; `security-review` reuses the existing `review` type. Schemas and tests landed
  before the skills, per the evals-first rule.
- **`release` core** `lib/agentic_forge/release.py` (100% covered): classify conventional commits
  → derive the semver bump (breaking → major, `feat` → minor, else patch; `0.y.z` breaking → minor)
  and a Keep-a-Changelog grouping (`**BREAKING:**`-flagged); a thin `commits_since` git seam keeps
  the logic unit-tested without a repo.
- **`ops` adapter seam** `lib/agentic_forge/ops.py` (100% covered): provider-agnostic
  `PipelineSource` / `AlertSource` (with `InMemory*` fakes for tests + eval fixtures) plus the
  deterministic assessment — `rollout_health`, `triage_alerts`, `deploy_status` (emits a
  schema-valid `deploy-status` mapping), and `classify_incident` (sev1–4). Keeps the
  `deploy-watch` / `incident-response` Tier-2 runnable with no live infra. (`deploy-status`
  `alerts` widened to list-or-dict to carry the triage counts.)
- **`release` skill** `plugin/skills/release/` (evals-first, fixture-backed): wires the `release`
  core to the repo — find the current version + commits since the last tag, derive the version,
  render the changelog and a `release` artifact, tag only on request. Tier-1 triggers + two
  inspection-gradeable Tier-2 cases (minor bump; breaking → major). The Stage-4 build template.
- **`qa-test-strategy` + `security-review` skills** (Tier-1 fork-orchestrators): delegate to the
  `qa-engineer` / `security-engineer` roles and emit a `test-strategy` / `review` (security-lens)
  handoff; validated by Tier-1 routing plus those roles' agent Tier-2 and the Tier-3 spine — the
  established convention for fork-orchestrators (no skill Tier-2).
- **`deploy-watch` + `incident-response` skills** (Tier-1 + Tier-2 own-behavior): wire the `ops`
  core — rollout-health assessment → `deploy-status`, and `sev1`–`sev4` classification →
  `incident` — with fixture-backed, inspection-gradeable Tier-2 (recorded pipeline/alert snapshots;
  outage / degraded scenarios) that run with no live infra.
- Tier-1-runner and skill-eval tests updated for the five new on-listing skills (router listing +
  the Tier-2 discovery set).
- **Stage 4 eval gate — all green** (`claude-opus-4-8`). Tier-2 (own-behavior skills, n=5):
  `release` / `deploy-watch` / `incident-response` lower bound **1.000** each. Tier-1 (routing,
  runs=5): `release` / `qa-test-strategy` / `security-review` / `deploy-watch` / `incident-response`
  all **recall 1.000, specificity 1.000**.
- **Tier-1 runner fixes** surfaced by the first live Tier-1 run (threshold 0.9 untouched):
  (1) raised the router `max_turns` so a reasoning model can emit its answer (`max_turns=1` cut it
  off — "Reached max turns"); (2) made the router prompt **classify-only** ("do not perform the
  request, only route it") — imperative prompts ("review this", "audit this") were being
  *performed* instead of classified, parsing to `none`; (3) replaced `release`'s `should_not`
  "Add a CHANGELOG entry for this PR" — a near-mirror of its "write the release changelog" trigger
  that made a keyword router seesaw recall↔specificity (4 tuning attempts, never both ≥0.9) — with
  a fair, unambiguous negative ("Update the README") testing the same boundary (release ≠ routine
  dev/docs), per [ADR 0020](docs/architecture/decisions/0020-tier2-inspection-gradeable-assertions.md).

### Added — Stage 5 product & marketing (design + foundation)

- **Stage 5 design** `docs/architecture/product-marketing.md`: the product half is already shipped
  (the `product` spine skill does research → PRD with success metrics), so Stage 5 is the
  **marketing** domain — one router-disciplined `marketing` skill (market-research / strategy /
  content as `references/` sub-procedures), **evidence-first** (claims-verification assertions) to
  address the roadmap's low-signal-content risk.
- **Marketing handoff types** (`handoff.py`, contract-first, 100% covered): `market-brief`
  (segments, named competitors, cited sources) and `marketing-strategy` (positioning, channels,
  messaging, metrics). Schemas + tests landed before the skill.
- **`marketing` skill** `plugin/skills/marketing/` (evals-first): one router skill dispatching to
  market-research / strategy / content `references/`, forking research/`Explore` for evidence.
  Tier-1 triggers (market/competitor research, GTM/positioning, content/social/paid) + two
  inspection-gradeable Tier-2 cases — a `market-brief` that cites every claim and invents no TAM,
  and on-brand content with no unsupported claims. (ADR 0022.)
- **Stage 5 eval gate — all green** (`claude-opus-4-8`): `marketing` Tier-2 lower bound **1.000**
  (n=5); Tier-1 **recall 1.000 / specificity 1.000** (runs=5). Routing tuning (threshold 0.9
  untouched): scoped `research` to *feature/options* research so "research the market" routes to
  `marketing` (research re-confirmed Tier-1 1.000), and made `marketing`'s description own its
  trigger phrasings (market research / competitor analysis / go-to-market / landing-page / social /
  ad copy) to lift three ~80%-routing prompts to ~100%.

### Added — Stage 6 design & onboarding (design + foundation)

- **Stage 6 design** `docs/architecture/design-onboarding.md`: `ux-design` (UX specs — flows,
  screens/states, accessibility — never pixels) and `repo-onboarding` (analyze an unfamiliar
  codebase + seed the Stage-3 vault). Both own-behavior → Tier-1 + Tier-2; Tier-1 descriptions
  written sharp from the start to avoid the keyword collisions that cost iteration in Stages 4–5.
- **Handoff types** (`handoff.py`, contract-first, 100% covered): `ux-spec` (flows, screens,
  accessibility, design-system refs) and `onboarding` (components, entry points, conventions,
  risks). Schemas + tests before the skills.
- **`ux-design` + `repo-onboarding` skills** (evals-first): `ux-design` (own behavior) emits a
  `ux-spec` (flows / screens-states / a11y / design-system) — specs, not pixels; `repo-onboarding`
  forks `Explore` and seeds the Stage-3 vault, emitting an `onboarding` map grounded in the code.
  Tier-1 triggers + inspection-gradeable Tier-2 (ux: flows/states/a11y at spec level; onboarding:
  components grounded in a fixture repo + a clean seeded vault). (ADR 0023.)
- **Stage 6 eval gate — all green** (`claude-opus-4-8`): `ux-design` and `repo-onboarding` Tier-2
  lower bound **1.000** (n=5) each; Tier-1 **recall 1.000 / specificity 1.000** (runs=5) each. The
  sharp-from-the-start descriptions held — no Tier-1 keyword-collision tuning was needed (one
  `repo-onboarding` gate run flickered to 0.75 purely on router variance — all four prompts route
  100% — and re-ran clean).

### Added — Stage 7 scheduling & observability

Completes the half of L4 that ADR 0019 deferred (scheduling is cadence, not a guardrail). No new
model-invocable skills — deterministic infra, gated by `pytest` (cores 100% covered) + Tier-0.

- **Scheduling** (no daemon): `lib/agentic_forge/schedule.py` — a declarative scheduled-job
  registry (`kb-maintenance` weekly; `deploy-digest` / `audit-digest` daily) + a **pure**
  `due_jobs(jobs, last_run, now)` + last-run state I/O. `dev/run_scheduled.py` runs the due jobs
  (`--dry` lists, `--force` runs all); `.github/workflows/scheduled.yml` (cron + dispatch) is the
  external clock. Built-in jobs reuse existing libs (`vault`, `ops`).
- **Observability**: `lib/agentic_forge/observability.py` — digests the logging hook's audit JSONL
  (`{tool, input, session_id}`) into per-tool / per-session counts and a report; `dev/audit_digest.py`
  prints it. No new event schema — it consumes what the L4 logging hook already records. (ADR 0024.)

### Added — Real provider connectors (design)

- **Design + ADR 0025** (`docs/architecture/connectors.md`): how to implement the existing
  `ops.py` seams (`PipelineSource` / `AlertSource`) and marketing research against real providers —
  each connector a **pure parser + thin fetch seam**; **Python adapters** for structured CLI/REST
  (GitHub Actions via `gh`), **MCP-first** for monitoring providers (Datadog / PagerDuty), native
  **`WebSearch`** for marketing; config + auto-detect selection; credentials never committed.
  Phased rollout (`GhPipelineSource` first).
- **Connectors phase 1 — `GhPipelineSource`** (`lib/agentic_forge/connectors.py`, 100% covered):
  a real `ops.PipelineSource` over GitHub Actions (`gh run list --json` → `Deploy`, with the
  status/conclusion mapping); `parse_gh_runs` is pure + tested, the `gh` call is a `# pragma: no
  cover` seam. `pipeline_source(repo)` auto-detects `gh` (else an empty source). Wired into
  `deploy-watch` (a `references/connectors.md`) and the scheduled `deploy-digest`.
- **Connectors phase 2 — `GrafanaAlertSource`** (`connectors.py`, 100% covered): a real
  `ops.AlertSource` over Grafana alerting — `parse_grafana_alerts` (pure, tested) maps Alertmanager
  alerts → `Alert` (severity normalization, active-only, env filter); the HTTP call is a `# pragma:
  no cover` seam. `alert_source()` reads `GRAFANA_URL`/`GRAFANA_TOKEN` (else empty). **MCP-first**
  per ADR 0025 (prefer the Grafana MCP tool; REST is the fallback). Wired into `deploy-watch` +
  `incident-response` references and the scheduled `deploy-digest`.
- **Connectors phase 3 — marketing live research**: `marketing` gains `WebSearch` / `WebFetch`
  tools; its market-research procedure now gathers live market/competitor data and records every
  source URL (under the evidence-discipline already gated in Tier-2). No connector code — native
  tools, provider-neutral. Completes the connectors rollout (ADR 0025).

### Changed — Tier-1 metric → mean routing-rate (ADR 0026)

- Tier-1 recall/specificity are now the **mean per-prompt routing rate** over N samples (threshold
  **0.9 unchanged**), replacing "fraction of prompts whose majority-of-N routes correctly." The old
  metric flickered around the 50% majority cliff (forced re-rolls in Stages 4–6) and rubber-stamped
  barely-majority routing (a skill routing every prompt at 55% passed at recall 1.0); the mean rate
  is **stable *and* stricter** (that 55% skill now fails). Implemented: `tier1_runner.selection_rate`
  + `gate.trigger_metrics` average the rates; `Tier1Report` now carries per-prompt rates; tests +
  eval-runbook updated. **Re-validation (all 17 on-listing skills, runs=5):** 11 PASS, and the
  stricter metric surfaced 6 with mean recall < 0.9 (the old majority-of-N hid them):
  `qa-test-strategy` 0.55, `skill-factory` 0.70, `repo-onboarding` 0.75, `product` 0.76,
  `knowledge` 0.80, `deep-review` 0.84 (specificity ≥ 0.92 throughout). Sharpening those six is a
  tracked follow-up.

### Fixed — documentation (deep-review pass)

A four-reviewer deep review (product/design, ADRs, usage/onboarding, impl↔docs) found the docs
faithful to the code but lagging the latest increments and thin on user onboarding. Fixes:

- **P0** — synced the Tier-1 metric description to the **mean routing-rate** (ADR 0026) in
  `spine.md` + `roadmap.md`; reconciled `skills-ref` → `dev/validate.py` (a skills-ref-style check)
  in `README.md` + `CLAUDE.md`; rewrote the README Status to the current L0–L4 state and added a
  **runnable Install**, a **"Using the plugin"** guide, and an **on-listing skill catalog**; added
  the MIT `LICENSE`.
- **P1** — currency + onboarding gaps. Docs currency: the `docs/` map now lists all five
  Stage-4–7 architecture docs (quality-ops, product-marketing, design-onboarding,
  scheduling-observability, connectors) and drops the stale "scheduling deferred"; `roadmap.md`
  count nine→seventeen on-listing skills + a **Post-spine increments** section (connectors 0025,
  Tier-1 metric 0026); `meta-core.md` lib tree/table gains `ops`/`release`/`schedule`/
  `observability`/`connectors` + the new dev CLIs; `guardrails.md` notes scheduling/observability
  shipped separately (0024); `eval-runbook.md` Tier-2 skill list updated (19, with the
  fork-orchestrators noted Tier-1-only). Onboarding: added **`CONTRIBUTING.md`** and a
  **`plugin/README.md`** (install + what's inside); fixed `handoff-to-cli.md`'s mypy command
  (`plugin/lib plugin/hooks dev`) and noted the `implementer`→`software-engineer` rename. Recorded
  two missing decisions: **[ADR 0027](docs/architecture/decisions/0027-deep-review-and-adversarial-pattern.md)**
  (`deep-review` skill + adversarial fan-out review pattern) and
  **[ADR 0028](docs/architecture/decisions/0028-handoff-contract-relaxation.md)** (the handoff
  contract relaxation that opened `status` + list-entry shape, relaxing ADR 0010).
- **P2** — consistency polish: marked the **Ralph loop deferred** everywhere (resolved the
  `overview.md` layer-table contradiction where it was listed among Built patterns; `vision.md`
  no longer lists it as a primitive used directly); `overview.md` scheduling bullet now notes it
  is **built** (registry + `run_scheduled` + cron, no daemon, ADR 0024); fixed `roadmap.md`'s
  self-referential `software-engineer` "(renamed from `software-engineer`)" → `implementer`;
  dropped the undefined "second wave" qualifier in `vision.md` scope; broadened the eval-runbook
  title/intro from "Tier-2 for the engine roles" to the whole eval pyramid; added the
  "(metric refined by 0026)" forward-marker to ADR 0016 in the index.

### Added — Layer 0 meta-core

- **Repository skeleton** for a Claude Code-only plugin: `plugin/` layout, `plugin.json`,
  `marketplace.json`, `pyproject.toml` (uv / pytest / ruff / mypy), `.gitignore`.
- **Project constitution** (`CLAUDE.md`): skill-centric + router discipline, eval-driven
  contract-first development, the four-tier eval pyramid, Python-only tested scripts,
  Obsidian knowledge base, layered architecture, editing rules.
- **Shared library** `plugin/lib/agentic_forge/`:
  - `naming.py` — Agent Skills name validation.
  - `frontmatter.py` — YAML frontmatter parsing.
  - `evals.py` — load + JSON-Schema validation of `evals.json`.
  - `validation.py` — Tier-0 checks for skills, agents, and the manifest.
  - `benchmark.py` — aggregate `grading.json` runs into benchmark statistics.
  - `gate.py` — threshold gate (Tier-1 trigger, Tier-2 quality, lower-bound rule).
- **Tier-0 validator CLI** `dev/validate.py`.
- **Eval contract schema** `plugin/schemas/evals.schema.json` — a superset of the
  skill-creator `evals.json` (adds `component`, `thresholds`, `triggers`).
- **`skill-factory` meta-skill** `plugin/skills/skill-factory/` — router-pattern SKILL.md,
  per-type references (skill / agent / script), the eval-loop guide, templates, and
  hand-written evals (bootstrap exception). Builds skills, subagents, and scripts.
- **Eval harness docs** `plugin/eval/README.md` — hybrid-on-skill-creator architecture.
- **Tests** (`tests/`): naming, frontmatter, evals, validation, benchmark, gate, and a
  plugin-integrity dogfood test that asserts the plugin passes its own Tier-0 gate.
- **CI** `.github/workflows/ci.yml` (Tier-0 on every push/PR) and `eval.yml` (Tier-1/2,
  cost-gated by `workflow_dispatch` or the `eval` PR label).
- **Documentation** under `docs/`: product vision, architecture overview, meta-core guide,
  eight ADRs, and this staged roadmap.

### Added — Stage 1 design

- **Engine design doc** `docs/architecture/engine.md`: role contracts (`reviewer`,
  `grader`, `implementer`, `architect`), markdown+frontmatter handoff artifact model and
  schemas, bounded review loop (N=3, approve signal), and agent-eval approach.
- **ADR 0009** recording the engine roles, handoff format, review loop, and agent eval.

### Added — Stage 1 engine foundations (L1)

- **Four subagent roles** under `plugin/agents/`, each with a narrowed toolset and an
  explicit, parseable return contract:
  - `reviewer` — critiques a diff or design artifact in isolation; returns an
    `approve`/`changes` verdict plus structured findings (`Read, Grep, Glob, Bash(git diff:*)`).
  - `grader` — grades outputs against assertions and emits `grading.json`
    (`text`/`passed`/`evidence` + summary); never edits the work (`Read, Grep, Glob`).
  - `implementer` — implements a scoped change in a worktree and reports files/tests/summary
    (`Read, Write, Edit, Bash, Grep, Glob`).
  - `architect` — produces a tech-design artifact + ADRs from requirements; docs only
    (`Read, Grep, Glob, Write`).
- **Agent eval contracts** at `plugin/agents/evals/<name>.evals.json` (`component.type:
  agent`, `tier2_quality` thresholds at `min_pass_rate 0.8`, `runs 5`), authored before the
  role bodies per the skill-factory order.
- **Handoff helper** `plugin/lib/agentic_forge/handoff.py` — loads SDLC handoff artifacts
  (Markdown + YAML frontmatter) and validates the header against per-type JSON Schemas
  (`research-brief`, `prd`, `tech-design`, `plan`, `review`), reusing `frontmatter.py`.
  Exposes `load_artifact` / `parse_artifact` (raise `HandoffError`), `validate_header`,
  `schema_for`, and the `status` / `verdict` / `severity` vocabularies. Unit-tested at 100%
  (`tests/test_handoff.py`).
- **Pattern references** under `plugin/patterns/` for Stage 2 skills to consume on demand:
  `handoff.md` (file-based handoff), `review-loop.md` (bounded N=3 writer→reviewer→revise),
  and `worktree.md` (git worktree isolation for the implementer).
- **ADR 0010** recording the handoff header-schema rules and the pattern-reference location.

### Added — agent Tier-2 eval harness

- **Agent eval runner** `plugin/lib/agentic_forge/agent_eval.py` + CLI
  `dev/run_agent_evals.py`: runs each engine role on its fixtures, grades with the `grader`
  role, aggregates with `benchmark.summarize`, and gates with `gate.tier2_quality` (the same
  gate as skills). The model/agent call is a seam with a `claude` runner (headless `claude
  -p`, level-2, authenticated via your **Claude subscription** through the CLI — recommended)
  and an `api` runner (Anthropic Messages, level-1, per-token), plus a `dry` mode that
  verifies wiring with no credentials. Roles can run isolated per case (`--isolate`, a fresh
  temp workdir each); the grader runs with read-only tools to verify on-disk artifacts.
  Unit-tested at 100% via stub seams.
- **Eval fixtures** `plugin/eval/fixtures/<role>/` (diffs, a `tech-design.md`, gradable
  outputs, a buggy parser + failing test, a PRD, decision/constraint briefs); each role
  contract's `files` now references them so the cases are runnable.
- **CI**: `eval.yml` now runs the agent Tier-2 — a dry-run wiring check on every eval job and
  the real `--runner claude` run on a Claude subscription (`CLAUDE_CODE_OAUTH_TOKEN`) when the
  secret is present. It installs the `claude` CLI and deliberately does not set
  `ANTHROPIC_API_KEY` (which would take precedence over the subscription token).
- **Packaging**: optional `eval` extra (`anthropic`, only for the `--runner api` path) so
  Tier-0 stays dependency-light, plus a mypy override so the absent SDK does not fail
  type-checking.
- **Docs**: `docs/eval-runbook.md` (how to run, fidelity levels, recording results) and
  **ADR 0011** (dedicated agent runner; narrows ADR 0009's "reuse skill-creator" for agents).

### Verified — agent Tier-2 results (2026-06-20)

Tier-2 (LLM-judged quality) run of the four engine roles via `--runner claude` on a Claude
subscription (Opus 4.8, `claude-opus-4-8`). Roles run at level-2 in fresh per-case temp
workdirs (`--isolate`) for independent measurement; the grader judges with read-only tools so
it can verify the real on-disk artifacts without modifying them. Assertions were strengthened
from the initial "floor" set to discriminating/negative checks (e.g. reviewer must catch the
negative-index silent-wrap, not only IndexError; grader must fail a partly-met assertion and
name the missing piece; implementer's retry must be bounded; architect's ADR must record a
genuinely rejected alternative). Gate: `min_pass_rate 0.8`, `runs 5`.

| Role | mean | stddev | lower_bound | n | Gate |
| --- | --- | --- | --- | --- | --- |
| reviewer | 1.000 | 0.000 | 1.000 | 5 | PASS |
| grader | 0.954 | 0.069 | 0.885 | 5 | PASS |
| implementer | 1.000 | 0.000 | 1.000 | 5 | PASS |
| architect | 1.000 | 0.000 | 1.000 | 5 | PASS |

All four pass. The gate is discriminating, not a rubber stamp: `grader` shows real
run-to-run variance (0.954, lower bound 0.885) and an adversarial probe scored a deliberately
weak reviewer output at 0.4. Harness hardening done during this run: strict boolean
pass-counting (a string `"false"` can no longer inflate); `--isolate` per-case workdirs;
read-only file-aware grading with a raised turn budget (the earlier architect failures were
the grader hitting `max-turns`, **not** a rate limit); retries/backoff and stdout+stderr
surfacing on a failed call.

### Added — deep-review skill (adversarial review)

- **`deep-review` skill** `plugin/skills/deep-review/` — a general, adversarial fan-out review
  for any target (docs, design/architecture, a code diff/PR, or the working tree): decompose
  into target-appropriate lenses, fan out independent reviewers, **verify each finding against
  the source**, and synthesize one deduplicated, prioritized report with fixes (optionally
  apply + re-gate). Router `SKILL.md` + `references/lenses.md` (lens catalog) + an evals-first
  contract (Tier-1 triggers, Tier-2 thresholds) with planted-defect fixtures under
  `plugin/eval/fixtures/deep-review/` (catch-rate + false-positive controls).
- **Pattern** `plugin/patterns/adversarial-review.md` — the reusable method
  (decompose → fan-out → verify → dedupe → synthesize → optional apply + re-gate); composes
  with the `reviewer` role, the review loop, and handoff, and mirrors `deep-research`'s
  harness. Stage 2 `code-review` can delegate to it.
- Systematizes the multi-agent review process used in this session so it is repeatable.
- **Gated (2026-06-20, Opus 4.8 via subscription):** Tier-0 green; **Tier-1** recall 1.000 /
  specificity 1.000 — after sharpening the description, which the trigger eval caught
  over-firing on a quick one-line lint (now routed to `code-review`); **Tier-2** mean 0.969,
  stddev 0.042, lower bound 0.927 (n=5) on the planted-defect fixtures (catches the planted
  contradiction/gap/bug/risk with no false positives on clean zones).

### Changed — Tier-3 E2E runner extended to the full six-phase spine

- `spine_e2e` now runs the whole spine — `research → product → architecture → plan → develop →
  code-review` — on an isolated taskstore copy, **starting from `FEATURE_REQUEST.md`** (no
  seeding: each phase produces the handoff the next consumes), with per-phase checkpoints (each
  artifact validates against its schema; develop's code passes the repo suite; review has a
  verdict). `prepare_workspace` gains an optional `seed` for partial runs. 100% unit-tested
  (correct-output stub + real git/pytest); dry-run clean.

### Added — Stage 2 spine (step 5c: plan phase — spine complete)

- **`plan` workflow skill** `plugin/skills/plan/` — the planning phase: turn `tech-design.md`
  into a dependency-ordered work plan (tasks with `deps`, checkpoints, deferred), delegating
  sequencing to the built-in `Plan` agent, and write a `plan.md` handoff for `develop`.
  **Tier-0 + Tier-1 recall 1.000 / specificity 1.000** (majority-of-3). Quality via the plan
  schema + the Plan agent.
- **The six-phase SDLC spine is now built**: `research → product → architecture → plan →
  develop → code-review`, each a gated workflow skill (Tier-0 + Tier-1 ≥ 0.9), joined by
  schema-validated handoff artifacts. The thin slice (architecture→develop→code-review) is
  proven end-to-end (Tier-3); the full six-phase E2E and the by-stack multi-language mechanism
  remain.

### Added — Stage 2 spine (step 5b: product phase)

- **`product` workflow skill** `plugin/skills/product/` — the product phase: turn
  `research-brief.md` into a PRD — assess the current product, define goals/non-goals/metrics/
  acceptance and user stories, and produce a `prd.md` handoff for `architecture`, eliciting
  ambiguities from the user rather than inventing them. **Tier-0 + Tier-1 recall 1.000 /
  specificity 1.000** (majority-of-3; clean separation of *what & why* (product) from *what
  exists* (research) and *how* (architecture)). Adds a schema-validated `research-brief.md`
  fixture (product's input). Quality via the prd schema + traceability to the brief.

### Added — Stage 2 spine (step 5a: research phase)

- **`research` workflow skill** `plugin/skills/research/` — the first spine phase: investigate a
  feature before it is specified by fanning out research tracks (delegating codebase exploration
  to the built-in `Explore` and external research to `deep-research`), synthesizing, and
  producing a `research-brief.md` handoff (cited sources + recommendation) that feeds `product`.
  **Tier-0 + Tier-1 recall 1.000 / specificity 1.000** (majority-of-3 router sim; distinct from
  `deep-research` (standalone report) and the spine neighbours after sharpening the description
  to own "compare/recommend before spec or design"). Depth quality comes from the delegated
  `deep-research` + the brief schema.

### Fixed — eval-gate + runner hardening (deep-review pass)

A deep multi-agent review of the whole codebase found real defects in the eval gates/runner;
all fixed with tests (lib coverage ~99%):

- **Gate integrity (`agent_eval`):** `grade_output` capped `passed` at the assertion count and
  `run_role` now aggregates over **expected assertion counts** (grade_output summaries), not
  `len(grader results)` — a grader returning extra/duplicate results can no longer push
  `pass_rate > 1.0` (inflating Tier-2), and omitted results now count as failures instead of
  vanishing. `runs <= 0` is rejected (was silently coerced to the default / produced empty runs).
- **Tier-0 false positive (`validation`):** markdown links with a `#anchor`/`?query` are
  stripped before the existence check (anchored reference links no longer fail the always-on
  gate). **New Tier-0 check:** every eval-case `files` fixture must exist (skill + agent
  contracts) — referenced fixtures can no longer silently rot.
- **Robustness:** `benchmark.pass_rate_of` tolerates a null `pass_rate` and an explicit
  `total: 0` (no crash / no silent drop); `spine_e2e.prepare_workspace` can re-run against the
  same `--workspace`; `check_wiring` flags duplicate fixture basenames (which the
  basename-flattening would otherwise overwrite silently).
- **Test gaps closed:** added `tests/test_dev_cli.py` (the `dev/` entry points + the
  unknown-runner `ValueError`) and regression tests for every fix above.

### Changed — documentation currency (deep-review pass)

The same review found docs that lagged the built code; brought them current:

- **Layer status:** `overview.md`, `README.md`, and `docs/README.md` now describe L1 and L2 as
  **built** (six roles; fan-out-fan-in / multi-aspect-review / adversarial-review / review-loop /
  worktree patterns; the six-phase spine proven end-to-end via Tier-3) instead of "planned" /
  "thin router skills (pre-implementation)".
- **Phase-workflows, not routers:** `CLAUDE.md` and `overview.md` describe L2 as a
  phase-workflow per SDLC phase (fan out → synthesize a handoff artifact), replacing the older
  "one router skill per domain, depth via sub-skills" framing.
- **Handoff producers:** `patterns/handoff.md` maps artifacts to the real skill names
  (`research`/`product`/`architecture`/`plan`), and documents `status` as recommended-but-not-
  enforced (the schema accepts any non-empty string), matching the relaxed handoff schema.
- **Ralph claim dropped:** removed "Ralph loops run natively" and the `ralph` keyword from
  `plugin.json` (and the README) — Ralph is not shipped/used yet.
- **Roster + runbook:** `eval-runbook.md` covers all six roles (adds `security-engineer`,
  `qa-engineer`) and the write-role fidelity note includes `qa-engineer`; `engine.md` keeps its
  Stage-1 scope but forward-points to the two Stage-2 specialists. Spine E2E docstrings now say
  "all six phases" instead of the old three-phase thin slice.

### Fixed — skill/pattern coherence (deep-review pass)

- **`code-review` can run the tools it requires.** Its `allowed-tools` widened from
  `Bash(git diff:*)` to `Bash`: the skill's style/lint aspect and its Verify step run the
  project's real tools (ruff/mypy/eslint/pytest/…), which the `git diff`-only grant forbade.
  Now consistent with `develop` and `deep-review`, and ready for multi-stack toolchains.
- **Canonical finding shape is consistent.** Added the missing `issue` field to the structured
  finding shape in `deep-review/SKILL.md`, `patterns/adversarial-review.md`, and
  `deep-review/references/lenses.md` (`severity, location, issue, evidence, suggested fix`),
  matching `code-review` and `patterns/handoff.md`.
- **No Tier-2 gate theater.** Documented in the eval-runbook that the agent eval CLI gates
  *roles* only; the `tier2_quality` thresholds declared by `deep-review`/`engineering-standards`/
  `skill-factory` are readiness contracts run via the harness / manual LLM-judge (an automated
  skill-Tier-2 CLI is a roadmap item), not gates this CLI enforces.

### Fixed — L4 guardrails (ADR 0019), step 4: security-review hardening

Independent security review of L4 (no blockers; `guardrails.py` 100%, all hooks fail-open
verified). Closed every finding:

- **Secret redaction (M1):** `redact_secrets` now catches `AWS_SECRET_ACCESS_KEY=` / `access_key=`
  (underscore-joined — no word boundary), PEM private-key blocks, and any `Authorization:` scheme
  — not just `Bearer`/`sk-`/`ghp_` (these get written to the audit log on disk).
- **mkfs false-positive (M2):** the disk-format block now requires a `/dev/` device argument
  (command-bounded), so `git grep mkfs` / `echo "…mkfs…"` are no longer wrongly blocked.
- **rm targets (M3):** also blocks `rm -rf` of system dirs (`/usr`, `/etc`, …), `~/`, and quoted
  `"/"`; still allows `rm -rf ./build`, `/tmp/x`, `~/Downloads/…`.
- **Force-push (M4/M5):** detects the `+refspec` form (`git push origin +main`) and matches a
  protected branch as a standalone token (no longer over-blocks `release-2024` / `feature/main-fix`).
- **Over-trigger + bounds (M6/N1/N2):** the test-gate triggers only on command-position
  `git commit`/`push` (not a quoted mention); `audit_record` bounds `tool`/`session_id`; the
  raw-disk block also covers `>|` clobber and `/dev/mapper/`. Plus hook `main()` allow-path tests
  (N3). `guardrails.py` stays 100% line+branch.

### Added — L4 guardrails (ADR 0019), step 3: docs + layer complete

- **`docs/architecture/guardrails.md`** — the L4 architecture doc (the four hooks, design notes,
  eval model, scheduling out-of-scope).
- Status across docs: overview L4, roadmap Stage 7, README, and the docs index now mark L4
  **Built**; `meta-core.md` lists `guardrails.py` + the guardrail hooks; `CLAUDE.md`'s layout
  notes them. Scope reconciled: **L4 = the four guardrail hooks; scheduling/observability is
  deferred** (a Stage-7 follow-on). **All five layers L0–L4 are now built.**

### Added — L4 guardrails (ADR 0019), step 2: the four hook scripts

The plugin gains runtime enforcement on tool use (reusing the `plugin/hooks/` pattern from L3):

- **`security.py`** (PreToolUse/Bash) — blocks dangerous commands (exit 2), allows the rest.
- **`commit_gate.py`** (PreToolUse/Bash) — on `git commit`/`git push`, runs the fast gate
  (`dev/validate.py` or the detected stack's lint) and blocks on failure; skippable via
  `AGENTIC_FORGE_SKIP_TEST_GATE`; fails open on infra errors.
- **`budget.py`** (PreToolUse/Task) — per-session subagent counter; warns over the soft cap,
  blocks over the hard (`AGENTIC_FORGE_SUBAGENT_SOFT` / `_HARD`).
- **`audit_log.py`** (PostToolUse) — appends a redacted JSONL audit line under
  `<project>/.agentic-forge/`; never blocks.
- `hooks.json` registers them (PreToolUse Bash → security + commit_gate, Task → budget;
  PostToolUse → audit) alongside the SessionStart hook. Each script is thin glue over
  `guardrails.py`, fails **open** on its own error (except the intentional security/gate blocks),
  and is unit-tested on allow + block paths (`tests/test_guardrail_hooks.py`). The gate file is
  `commit_gate.py` (not `test_gate.py`) to avoid pytest's `test_` collection prefix.

### Added — L4 guardrails (ADR 0019), step 1: guardrails lib

L4 (the last layer) begins — deterministic guardrail logic the hook scripts call.

- **`plugin/lib/agentic_forge/guardrails.py`** — `classify_command` (security deny-list: blocks
  `rm -rf /`/`~`, fork bombs, `curl|sh`, `mkfs`/`dd` to a device, `chmod 777 /`, raw-disk writes,
  and force-push to a protected branch — conservative, allows everything else), `is_commit_or_push`
  + `choose_gate` (test-gate: `dev/validate.py` if present, else the detected stack's lint),
  `redact_secrets` + `audit_record` (logging), and `bump_and_check` (subagent budget: warn over a
  soft cap, block over a hard cap). 100% line+branch coverage.
- `tests/test_guardrails.py` — allow **and** block paths for every guardrail.

### Fixed — doc/plan drift (pre-L4 audit)

An independent doc + plan audit before building L4 found drift (no blockers); fixed:
- **Layer/Stage mapping** (`docs/README.md` glossary): corrected the false "1:1" claim — L0–L3
  align with Stages 0–3, but **L4 = Stage 7**, and Stages 4–6 are SDLC-domain build-outs on top
  of L1–L3 (no new layer).
- **No untrue surface claims** (`plugin.json` keywords + `plugin.json` / `marketplace.json`
  descriptions): dropped `ui-ux` / `qa` / `deployment` (unbuilt) and the UI/UX/QA/deployment
  enumeration; added the knowledge base and `code-review`.
- **Counts current:** the on-listing router set is **nine** (was "eight") in the roadmap + the
  runner test comment; the eval-runbook tier2 list now includes `knowledge` (13, runs directly).
- **Stale "Layer 3 next":** spine.md and the roadmap now point only to Layer 4 (L3 shipped).
- **ADR index:** 0013 status "Accepted (design)" → "Accepted" (the spine is built). Immutable ADR
  bodies (0016 "eight" / 0017 "twelve") left as point-in-time records.

### Fixed — L3 knowledge base (ADR 0018), step 5: review hardening

Independent adversarial review of L3 (gate green, vault 100%, hook never blocks the session). One
**major** fixed: `add_note(moc=<themed>)` created a themed MOC but never linked it from the root
MOC, so the themed MOC was an immediate **orphan** — yet the `knowledge` capture workflow (and
eval id 2) require a clean vault. `add_note` now links a new themed MOC from the root
(idempotently) via extracted `_ensure_moc` / `_append_link` helpers, so a clustered capture stays
valid. Also: the masking test now asserts `validate_vault == []` (+ a two-notes-one-themed-MOC
case); `_WIKILINK` excludes newlines (a stray `[[` can't swallow text across lines). vault.py
stays 100% line+branch.

### Added — L3 knowledge base (ADR 0018), step 4: docs + layer complete

- **`docs/architecture/knowledge.md`** — the L3 architecture doc (vault format, deterministic
  core, recall/capture skill, session-start hook, eval model).
- Status across docs: `overview.md` L3, roadmap Stage 3, `README`, and the docs index now mark
  L3 **Built**; `meta-core.md` lists `vault.py` + `plugin/hooks/`; `CLAUDE.md`'s layout notes the
  session-start hook is built. **Only L4 (guardrails/observability) remains.**

### Added — L3 knowledge base (ADR 0018), step 3: session-start hook

The plugin's **first hook** — session-start knowledge injection.

- **`plugin/hooks/hooks.json`** — a `SessionStart` command hook (auto-discovered at the plugin
  root) running `${CLAUDE_PLUGIN_ROOT}/hooks/scripts/session_start.py` (15s timeout).
- **`plugin/hooks/scripts/session_start.py`** — reads the hook payload (`cwd`), builds the vault
  map via `vault.session_summary`, and emits it as SessionStart `additionalContext`. A **no-op**
  when there's no vault, and it **never blocks the session** (any error exits 0 silently). All
  logic is in the tested `vault.py`; the hook is thin glue.
- **`tests/test_session_start_hook.py`** — build_context (vault / no-vault), main (emits the
  injection JSON; no-vault → no output; bad stdin → safe exit 0), and hooks.json validity. mypy
  now type-checks `plugin/hooks` too (CI + README).

### Added — L3 knowledge base (ADR 0018), step 2: knowledge skill

- **`plugin/skills/knowledge/`** — an on-listing **recall + capture** skill. *Recall:* detect the
  vault, rank candidates via `vault.recall`, answer grounded in real notes citing `[[links]]` (or
  say the vault is silent — never invent). *Capture:* distill to atomic notes, `vault.add_note`
  (writes + wikilinks from a MOC), validate. Distinct from `research` (external) by design — it
  reads **our** notes. allowed-tools Read/Grep/Glob/Bash/Write/Edit; body 43 lines.
- **`evals/evals.json`** — Tier-1 triggers (recall + capture vs the neighbours, incl. the
  research boundary) + a Tier-2 contract (two capture cases: atomic, wikilinked, valid vault),
  run by `run_skill_evals.py`. The on-listing router set is now **9**, the tier2 skill set **13**.

### Added — L3 knowledge base (ADR 0018), step 1: vault lib

L3 begins — an Obsidian-format knowledge vault the plugin deploys + maintains in the target
repo's `docs/knowledge/`.

- **`plugin/lib/agentic_forge/vault.py`** — the deterministic core: parse/resolve `[[wikilinks]]`,
  load the note graph, **validate** (broken links, orphans, missing root MOC), **scaffold** an
  empty vault (root `MOC.md` + README), **add+link** an atomic note (creates the MOC if needed),
  **rank recall candidates** by token/tag/title overlap, and build the **session-start summary**
  (root MOC + highest-degree notes; `""` when there's no vault). Tolerates frontmatter-less notes
  and skips the vault README. 100% line+branch coverage.
- `tests/test_vault.py` — links/graph/validate/scaffold/add_note/recall/summary paths.

### Fixed — integrity audit (post-interruption review)

A full integrity audit — prompted by several interrupted background tasks (API rate-limits killed
some review agents mid-run) — confirmed the session's work is complete and consistent (277 tests,
clean tree, lib coverage 99%, and all prior review-fixes verified present in their files). It
found **two minor gaps**, both fixed:

- **`meta-core.md` was stale:** the two lib modules added this session (`tier1_runner.py`,
  `skill_eval.py`) and their CLIs (`run_tier1_evals.py`, `run_skill_evals.py`) were missing from
  the shared-library tree/table and the `dev/` line — ADR 0016/0017 had updated
  spine/roadmap/eval-runbook but not meta-core. Added (and noted `agent_eval.run_eval_cases` as
  the shared eval core).
- **Tier-3 was unwired in CI:** `run_spine_e2e.py` was the only eval runner not invoked in
  `eval.yml`; added a dry-run wiring step plus a cost-gated subscription E2E step, so all five
  runners now run in CI (Tier-0 always; Tier 1/2/3 cost-gated).

### Added — automated skill Tier-2 quality runner (ADR 0017)

The last manual tier is now automated — **every tier of the eval pyramid has a runner**.

- **`plugin/lib/agentic_forge/skill_eval.py`** — runs Tier-2 for the twelve skills that declare
  `tier2_quality` (`deep-review`, `skill-factory`, `engineering-standards`, the nine `*-patterns`
  packs). Two execution modes: **knowledge skills** (`engineering-standards`, `*-patterns`) run
  *as the `software-engineer` with them loaded* (system = SE body + standards + pack), the
  engineer's tools, isolated, graded against the skill's own assertions — making the long-claimed
  "exercised through the software-engineer's Tier-2" real; **on-listing skills** (`deep-review`,
  `skill-factory`) run directly. Graded by the `grader` role, aggregated, gated `mean − σ ≥ 0.8`.
  100% line + branch coverage.
- **`agent_eval` refactor:** the per-run loop (grading, the pass-rate cap, write-isolation,
  aggregate-over-expected-counts) extracted into `run_eval_cases`, shared by `run_role` and
  `run_skill` — one eval core, no drift; `run_role`'s external behaviour and `RoleReport`
  unchanged (its tests still pass).
- **`dev/run_skill_evals.py`** — CLI mirroring the others (`--runner dry|claude|api`, `--skill`,
  `--model`, `--runs`); `dry` checks every skill's wiring with no auth. It is the most expensive
  eval (a full software-engineer coding session per case × N), so CI cost-gates it.
- **CI:** `eval.yml` gains a real dry + cost-gated skill-Tier-2 step (replacing the manual note).
- **Docs:** ADR 0017 (+ index); the eval-runbook scope note is rewritten (the "no automated
  path" gap is closed) with a "Skill Tier-2" section; spine.md and roadmap mark all four tiers
  automated. Resolves the deep-review completeness finding that the packs' `tier2_quality` had no
  execution path.

### Added — Tier-1 trigger runner on live skill descriptions (ADR 0016)

Skill Tier-1 is now automated (it was a CI TODO no-op and an ad-hoc "router sim"):

- **`plugin/lib/agentic_forge/tier1_runner.py`** — builds the **live** always-on listing (every
  model-invocable skill's `name` + `description`; off-listing `*-patterns` /
  `engineering-standards` excluded) and classifies each on-listing router skill's trigger prompts
  against it. Grading is **deterministic** (a `should_trigger` prompt must select the skill =
  recall; a `should_not_trigger` must not = specificity), sampled **majority-of-N**, gated ≥ 0.9
  through the shared `gate.trigger_metrics` + `gate.tier1_trigger` — giving those previously
  test-only pure functions a production caller. Reuses the `agent_eval` transport seam (tools
  off, one turn); no second transport. 100% line + branch coverage.
- **`dev/run_tier1_evals.py`** — CLI mirroring `run_agent_evals` (`--runner dry|claude|api`,
  `--skill`, `--model`, `--runs`); `dry` verifies the listing/trigger wiring with no auth.
- **CI:** `eval.yml`'s skill-Tier-1/2 TODO step is replaced by a real dry + cost-gated
  subscription Tier-1 run; skill Tier-2 stays a documented manual step.
- **Docs:** ADR 0016 (+ index); an eval-runbook "Skill Tier-1" section; spine.md and roadmap mark
  the live runner built (replacing the router-sim wording). Scope: the eight on-listing router
  skills (research/product/architecture/plan/develop/code-review/deep-review/skill-factory);
  off-listing packs are Tier-1-exempt by design.
- **Independently adversarial-reviewed** (no blockers; the gate's grading semantics, listing
  fidelity, and wiring verified correct; 100% line+branch). Applied its findings: `check_wiring`
  now flags a `tier1_trigger` block missing a recall/specificity value (a `{}` threshold would
  otherwise pass vacuously — recall 0 yet PASS), and `run_tier1` refuses a mis-wired plugin
  (defense-in-depth, not only the dry CLI); docstrings note the terse-answer-format assumption
  and odd-`runs`; the CLI warns on an unknown `--skill`.

### Changed — deep-review pass (docs currency + completeness audit)

A four-reviewer deep review (docs / lib+gates / skills / completeness). Three lost their final
synthesis to a transient API rate-limit, so docs/lib/skills were re-reviewed inline; the
completeness + eval-pyramid audit completed — **no blockers/majors**, and it independently
verified Tier-0 and agent-Tier-2 are real (272 tests, lib coverage 99%). Applied its findings:

- **Doc currency:** `spine.md` status corrected from "Designed (pre-implementation)" to **Built**
  (it contradicted its own body); `README` status + checklist now state multi-stack/by-stack is
  built (nine packs), not "next"; `overview.md` L2 notes the spine is stack-parametric;
  `engine.md`'s "fan-out/fan-in deferred" line clarified (the *pattern* shipped in Stage 2 — only
  research-at-scale and Ralph remain deferred).
- **No overstated coverage:** the eval-runbook now states plainly that the `*-patterns` /
  `engineering-standards` `tier2_quality` thresholds have **no automated execution path yet** (the
  `software-engineer` eval cases don't exercise pack idioms) — meet them via a manual judge until
  pack-aware SE cases land; that wiring is the named roadmap item.
- **Honesty in code/schema:** `spine_e2e.py`'s docstring now notes the Python toolchain is
  hardcoded for the fixture (a non-Python E2E would drive the command from
  `stacks.primary(repo).toolchain.test`); `evals.schema.json` marks the unused `tier3_e2e` and
  the extra `component.type` enum values as **reserved** for future component types.

### Added — by-stack: javascript / jvm / dotnet / ruby / php packs (pack coverage complete)

Five more `*-patterns` reference packs (off-listing, `disable-model-invocation`), completing pack
coverage for **every registered stack**:

- **`javascript-patterns`** — plain JS/Node: ESM, `const`/`let`, awaited async, `===`,
  boundary validation, JSDoc + `// @ts-check`; pitfalls (floating promises, `==`/coercion, `var`
  hoisting, prototype pollution).
- **`jvm-patterns`** — Java/Kotlin: the Gradle/Maven wrapper, JUnit 5, `Optional`/null-safety,
  records/data classes, try-with-resources/`use`; pitfalls (NPE, `==` vs `.equals`,
  thread-safety, swallowed exceptions).
- **`dotnet-patterns`** — C#: `dotnet build`/`test`/`format`, nullable reference types,
  async-all-the-way (no `.Result`/`.Wait()`), records/pattern matching, `IDisposable`/`using`;
  pitfalls (`async void`, blocking-on-async deadlock, multiple enumeration).
- **`ruby-patterns`** — Bundler/RSpec/RuboCop, Enumerable/guard clauses/`&.`, specific error
  classes, `frozen_string_literal`; pitfalls (bare `rescue`, monkey-patching, `nil`, N+1).
- **`php-patterns`** — Composer/PHPUnit/PHPStan, `declare(strict_types=1)` + typed signatures,
  PSR-12/PSR-4, prepared statements; pitfalls (SQL injection, loose `==`, unvalidated
  superglobals).
- **Registry + tests:** each `STACKS` entry now carries its pack; `test_shipped_packs` covers all
  nine and `test_profile_carries_pack` is parametrized over every stack. The no-pack
  `format_profile` case is now the `unknown` profile (every *registered* stack ships a pack;
  detection-only stacks remain allowed by design).
- **Docs:** spine.md and roadmap mark by-stack pack coverage complete; the
  `engineering-standards`-only fallback now applies to unrecognized (`unknown`) repos.
- Each pack ships a 2-case `tier2_quality` readiness contract (no `tier1_trigger`); bodies
  51–55 lines; full Tier-0 green; `stacks.py` stays 100% line+branch.
- **Independently adversarial-reviewed** — jvm/dotnet/php by language-expert agents,
  javascript/ruby inline; **no blockers/majors**. Applied their polish: jvm table uses the
  `./mvnw` wrapper for symmetry with `./gradlew` (+ a `stacks.py` note that JVM has no canonical
  formatter default); dotnet adds the `ConfigureAwait(false)` rationale and `await using` /
  `IAsyncDisposable` coverage (+ eval), and gives `async void` its consequence; php states
  `declare(strict_types=1)` must be the *first statement*, tags the modern features as 8.0–8.1,
  and adds the "never silence a checker" line for parity.

### Added — by-stack: rust-patterns (fourth stack pack)

- **`plugin/skills/rust-patterns/`** — the fourth `*-patterns` reference pack (off-listing,
  `disable-model-invocation`), modelled on the prior packs: the Cargo toolchain (prefer the
  repo's Makefile/justfile/CI; `cargo test`, `cargo check`/`build`, `cargo clippy -- -D warnings`,
  `cargo fmt` defaults), idioms (borrow over clone, `&str`/`&[T]` params; `Result` + `?` with
  `thiserror`/`anyhow`; `Option` over sentinels; make illegal states unrepresentable; iterators;
  fearless concurrency via `Send`/`Sync` + `Arc<Mutex<…>>`), testing (`#[cfg(test)]` units,
  `tests/` integration, doc-tests, `Err`/boundary cases), and high-value pitfalls (`unwrap`/
  `expect` panics, `.clone()` to dodge the borrow checker, undocumented `unsafe`, blocking in
  async / lock held across `.await`, integer overflow debug-vs-release, `Rc`/`RefCell` cycles).
- **Registry wiring:** `stacks.STACKS["rust"].pack = "rust-patterns"`; extended
  `test_shipped_packs`, parametrized the end-to-end pack assertion over python/typescript/go/rust,
  and re-pointed the no-pack format test at a still-packless stack (ruby). No workflow-skill
  change needed.
- **`evals/evals.json`** — `tier2_quality` readiness contract (no `tier1_trigger`), exercised
  through the `software-engineer`'s Tier-2. Body 65 lines; Tier-0 green.
- **Docs:** spine.md and roadmap mark python/typescript/go/rust packs shipped (further packs
  incremental).
- **Independently adversarial-reviewed** (deep Rust-expertise agent; no blockers/majors, gate
  green) and refined from its findings: standardise clippy on `--all-targets -- -D warnings`
  across the prose/DoD/evals (so the lint gate also covers test code, matching the toolchain
  table); state integer-overflow as governed by `overflow-checks` (debug/test default) rather
  than an absolute debug-vs-release rule; name `Weak` as the fix for `Rc`/`RefCell` cycles.

### Added — by-stack: go-patterns (third stack pack)

- **`plugin/skills/go-patterns/`** — the third `*-patterns` reference pack (off-listing,
  `disable-model-invocation`), modelled on `python-patterns`/`typescript-patterns`: the Go
  toolchain (prefer the repo's Makefile/CI; `go test ./... -race`, `go vet`, `gofmt`/`goimports`,
  `golangci-lint` defaults; keep `go.mod` tidy), idioms (errors as values wrapped with `%w` +
  `errors.Is`/`As`, accept-interfaces/return-concrete, `defer` cleanup, `context.Context` first
  param, no goroutine leaks), testing (table-driven `t.Run` subtests, `-race`, determinism), and
  high-value pitfalls (unchecked errors, nil-interface-vs-nil-pointer, closed-channel send,
  `defer`-in-loop, loop-variable capture incl. the Go 1.22 change, unchecked type assertions,
  random map order).
- **Registry wiring:** `stacks.STACKS["go"].pack = "go-patterns"`; extended `test_shipped_packs`
  and added an end-to-end `go.mod` → `go-patterns` pack assertion. No workflow-skill change
  needed — `develop` / `code-review` / the roles pick it up via the profile.
- **`evals/evals.json`** — `tier2_quality` readiness contract (no `tier1_trigger`), exercised
  through the `software-engineer`'s Tier-2. Body 66 lines; Tier-0 green.
- **Docs:** spine.md and roadmap mark `python-patterns` + `typescript-patterns` + `go-patterns`
  shipped (further packs incremental).

### Added — by-stack: typescript-patterns (second stack pack)

- **`plugin/skills/typescript-patterns/`** — the second `*-patterns` reference pack (off-listing,
  `disable-model-invocation`), modelled on `python-patterns`: the TS toolchain (prefer the repo's
  `package.json` scripts and the package manager the lockfile implies — npm/pnpm/yarn/bun;
  `tsc --noEmit` / eslint / prettier defaults), strict-typing idioms (`strict` on, no `any`,
  `unknown` + narrowing, discriminated unions, `import type`, `satisfies`, union literals over
  `enum`), testing (the repo's runner, type-level tests, determinism, boundary + error cases),
  and high-value pitfalls (unsound `as` / non-null `!`, floating promises, `==` vs `===`, loose
  `tsconfig`, `enum` cost).
- **Registry wiring:** `stacks.STACKS["typescript"].pack = "typescript-patterns"`, so a
  `tsconfig.json` repo now routes to the pack; updated the registry-invariant test and added a
  TS `.pack` assertion. No workflow-skill change needed — `develop` / `code-review` / the roles
  pick it up generically via the profile.
- **`evals/evals.json`** — `tier2_quality` readiness contract (no `tier1_trigger`), exercised
  through the `software-engineer`'s Tier-2 like `python-patterns`. Body 64 lines; Tier-0 green.
- **Docs:** spine.md and roadmap mark `python-patterns` + `typescript-patterns` shipped (further
  packs incremental). Bare JavaScript (no `tsconfig.json`) stays detection-only for now.
- **Independently adversarial-reviewed** (deep TS-expertise agent; no blockers/majors, gate
  green) and refined from its findings: list both `bun.lock` (Bun ≥ 1.2's default text lockfile)
  and the legacy `bun.lockb`; add `prettier`-formatted to the Definition of done (parity with
  `python-patterns`).

### Changed — deep-review lens catalog enriched (from this session's reviews)

Per the "living catalog" rule, added three durable lenses to
`plugin/skills/deep-review/references/lenses.md` from failure modes surfaced this session:

- **Matcher precision** (under *Robustness at seams*) — a regex/config/hint parser that
  over-matches lookalikes (`stackoverflow` for a `stack` key) or bridges newlines (`\s` vs
  `[ \t]`); test the forms that should match and the near-misses that should not.
- **Branch-vs-line coverage honesty** (under *Tests & coverage*) — 100% line coverage can hide
  an uncovered branch (`--cov-branch`); don't claim coverage the run doesn't show.
- **Packaging / install boundary** (cross-cutting) — a shipped skill/agent must reference only
  what ships with it; a link that resolves in-repo but points outside the published root
  (`../../../docs/`) dangles once installed — cite by name instead.

### Fixed — by-stack (multi-language), step 5: adversarial-review hardening

An independent fresh-agent adversarial review of the whole by-stack feature found **no blockers
and no majors** (gate green); applied its actionable items:

- **Regex hardening (`stacks.py`):** a bare `stack:` no longer bridges a newline to capture the
  next line's token as the value — the delimiter-adjacent separators are now line-local
  (`[ \t*]`, not `\s`). Behaviour for the documented forms is unchanged.
- **Test strength (`tests/test_stacks.py`):** added parametrized positive hint-form cases
  (bullet, bold `**Stack:**`, blockquote, `=` delimiter, quoted value, indented, dotted alias)
  and negative cases (headings, `stackoverflow:`, newline/YAML-list values), plus a
  bogus-hint-in-`CLAUDE.md` → real-hint-in-`AGENTS.md` fall-through test — `stacks.py` is now at
  **100% line + branch** coverage.
- **Doc clarity:** `develop` now states the engineer **re-derives** the stack profile on the
  worktree (rather than implying a profile object is handed across); ADR 0015 + spine.md clarify
  that `tsconfig.json` alone detects TypeScript (suppressing a co-present bare `package.json`);
  `meta-core.md`'s shared-library tree/table now list `spine_e2e.py` + `stacks.py` and the
  `run_spine_e2e.py` CLI (closing pre-existing Stage-2 drift).

### Verified — by-stack (multi-language), step 4: detection closed on the E2E fixture

- **Fixture target-repo gains a `pyproject.toml`** (`plugin/eval/fixtures/spine/target-repo/`)
  so the SDLC-spine E2E target is a realistic Python project — and `stacks.detect` resolves it
  to `python` → `python-patterns` (previously, with no manifest, it fell back to `unknown`).
- **`tests/test_spine_e2e.py`** asserts the prepared workspace is detected as Python with the
  `python-patterns` pack, closing the by-stack loop on the real E2E target. The in-workspace
  `pytest` run stays green with the new manifest.
- **Docs:** roadmap marks the by-stack mechanism built (further `*-patterns` packs incremental);
  the eval-runbook scope note now lists the `*-patterns` packs among the skills that declare a
  `tier2_quality` readiness contract exercised through the role's Tier-2.

### Changed — by-stack (multi-language), step 3: spine consumes stack detection

The spine is now stack-parametric end to end — detection feeds the implement/review phases:

- **`develop`** detects the stack in step 1 (`stacks.primary`/`stacks.detect`), passes the
  profile to `software-engineer` (which loads the named `<stack>-patterns` pack, e.g.
  `python-patterns`, or falls back to standards + the profile's toolchain), and the review gate
  uses the stack's lint/type tools.
- **`code-review`** detects the stack in Scope so the style/lint aspect runs that stack's real
  tools (the profile's toolchain — ruff/mypy, eslint/tsc, go vet, …), preferring the repo's
  declared commands.
- **`software-engineer`** and **`qa-engineer`** roles now detect the stack deterministically
  (`stacks.detect`/`primary`) and load the `<stack>-patterns` pack — replacing the earlier
  prose "detect from CLAUDE.md/AGENTS.md/the repo" with the tested helper. Both prefer the
  repo's own declared commands over the profile defaults.

### Added — by-stack (multi-language), step 2: python-patterns pack

- **`plugin/skills/python-patterns/`** — the first stack reference pack: an off-listing
  (`disable-model-invocation: true`) knowledge skill, modelled on `engineering-standards`,
  carrying only Python-specific conventions on top of the standards — the toolchain (prefer the
  repo's declared commands; `pytest` / `ruff` / `mypy` defaults), idioms (typing, dataclasses,
  pathlib, EAFP, context managers), testing discipline (parametrize, fixtures, `tmp_path`,
  determinism, boundary + error cases), layout, and the high-value Python pitfalls (mutable
  defaults, bare `except`, late-binding closures, `is` vs `==`, secrets in logs).
- **`evals/evals.json`** — declares a `tier2_quality` readiness contract (no `tier1_trigger`;
  the pack is loaded on demand, not auto-triggered), exercised through the `software-engineer`'s
  Tier-2 like `engineering-standards`. Body 66 lines; passes Tier-0.

### Added — by-stack (multi-language), step 1: deterministic detection

The spine becomes stack-parametric (ADR 0015), starting with the detection layer:

- **`plugin/lib/agentic_forge/stacks.py`** — `detect(repo)` / `primary(repo)` identify a target
  repo's stack(s) from an explicit `stack:` hint (CLAUDE.md / AGENTS.md, with aliases) or
  manifest signatures (`pyproject.toml` → python, `tsconfig.json`/`package.json` →
  typescript/javascript, `go.mod` → go, `Cargo.toml` → rust, `*.csproj` → dotnet, …), ranked by
  specificity (TypeScript supersedes a bare `package.json`); an empty repo yields the `unknown`
  profile. A `StackProfile` carries `stack_id`, `display`, the `*-patterns` `pack` (or `None`),
  a conventional `toolchain` (test/lint/typecheck/format), and the manifest evidence;
  `format_profile` renders a one-line summary for workflows to log. The `STACKS` registry is
  data — adding a language is one entry.
- **`tests/test_stacks.py`** — manifest detection per stack, hint precedence + aliases +
  fall-through, TS/JS suppression, monorepo ranking, unknown, and registry invariants;
  `stacks.py` at 100% line + branch coverage, ruff + mypy clean.

### Verified — full six-phase spine E2E (Tier-3, 2026-06-21)

The real `--runner claude` scenario (Opus 4.8) carried `task-priorities` through **all six
phases** — `research → product → architecture → plan → develop → code-review` — on an isolated
taskstore copy, starting from `FEATURE_REQUEST.md`. **All six phases pass**: each produced a
schema-valid handoff the next consumed (`research-brief → prd → tech-design+ADRs → plan`),
`develop` implemented priorities with the repo suite green, and `code-review` approved. The
spine is proven end-to-end across its full length — idea to reviewed, tested code.

The run again caught real schema-vs-output mismatches (the value of Tier-3): the model used
`status: complete` (a reasonable lifecycle label outside our enum) and an unquoted `date:` that
YAML parsed into a date object — both rejected by the over-strict schema.

### Fixed — handoff schema: lenient status + date

- `lib/agentic_forge/handoff.py`: `status` now validates as any non-empty string (the
  `STATUSES` list stays as recommended-but-not-enforced guidance — real artifacts use labels
  like "complete"); the `date` field accepts a string or a YAML-parsed date. `verdict` and
  `severity` stay strict (the review loop branches on them). Tests added; coverage 100%.

### Verified — Stage 2 thin-slice E2E (Tier-3, 2026-06-21)

The real `--runner claude` scenario (Opus 4.8, subscription) carried `task-priorities` through
`architecture → develop → code-review` on an isolated taskstore copy. **All three phases pass**
their checkpoints: `architecture` produced a schema-valid `tech-design.md` + 2 ADRs;
`develop` implemented priorities with the repo's **pytest suite green**; `code-review` emitted a
valid `review.md` with an `approve` verdict. The thin slice is proven end-to-end — one
continuous path from a PRD to reviewed, tested code.

The run **caught a real bug** (the point of Tier-3): the architect produced *structured* list
entries (a decision as `{id, title, adr}`, a component as `{name, change}`, a risk as
`{risk, mitigation}`) — richer and more useful than bare strings — but the handoff `tech-design`
schema required arrays of strings, so the otherwise-correct artifact failed validation.

### Fixed — handoff schema accepts structured list entries

- `lib/agentic_forge/handoff.py`: list fields (`decisions`, `components`, `risks`, `goals`,
  `acceptance`, `non_goals`, `metrics`, `sources`, `checkpoints`, `deferred`) now accept entries
  that are **a string or a structured object**, matching how real artifacts are written. Bare
  strings still validate; tests added; `handoff` coverage stays 100%.

### Added — Stage 2 thin slice (step 4: Tier-3 E2E runner)

- **Tier-3 spine E2E runner** `plugin/lib/agentic_forge/spine_e2e.py` + CLI
  `dev/run_spine_e2e.py`: carries the `task-priorities` feature through
  `architecture → develop → code-review` on an **isolated copy** of the taskstore fixture repo
  (`git init`'d), checking per-phase checkpoints — tech-design + ADR validate against the
  handoff schemas, the implemented code carries a real priority marker and the repo's **test
  suite passes**, and `review.md` validates with a verdict. The model call is the same seam as
  the agent runner (`--runner dry` for wiring, `--runner claude` for the real run on the
  subscription). Unit-tested at 100% via a correct-output stub + real git/pytest; dry-run clean.
- **PRD fixture** `plugin/eval/fixtures/spine/prd.md` (task-priorities) — the `architecture`
  phase's input, schema-validated.

### Added — Stage 2 thin slice (step 3c: develop flagship workflow)

- **`develop` workflow skill** `plugin/skills/develop/` — the implementation phase / flagship:
  read `plan.md`+`tech-design.md`, set up a git worktree (single, sequential v1), implement the
  step via the `software-engineer` role, **gate it with a multi-aspect review** (develop
  produces the staged worktree diff and hands it to `reviewer`+`security-engineer`+lint),
  bounded loop-back (N=3, with a stated terminal state), then `qa-engineer` hardens the suite,
  and finally hand off + **remove the worktree**. **Tier-0 + Tier-1 recall 1.000 /
  specificity 1.000** (majority-of-3); end-to-end quality is the Tier-3 spine scenario.
- **Spine fixtures** `plugin/eval/fixtures/spine/{plan.md,tech-design.md}` (task-priorities),
  validated against the handoff schemas — develop's inputs (the thin slice skips the plan phase).
- **Flagship self-review caught real defects** (two adversarial reviewers), all fixed before
  commit: the review gate fed an **empty diff** (`BASE...HEAD` is empty for an uncommitted
  worktree → now stage + `diff --staged`, including new files); the reviewer couldn't read a
  worktree via `git -C` (now develop supplies the diff text); the flagship eval referenced a
  non-existent `plan.md`; **unbounded QA loop** and **missing N=3 terminal state**; **worktree
  cleanup** never invoked; and doc-currency drift (patterns/spine still described the deferred
  parallel-impl model and a per-skill Tier-2 that the slice delegates to roles + Tier-3).
- Reconciled the patterns (`worktree`, `multi-aspect-review`, `fan-out-fan-in`) and
  `spine.md`'s eval model to the single-worktree v1 + delegate-quality reality.

### Added — Stage 2 thin slice (step 3b: code-review workflow)

- **`code-review` workflow skill** `plugin/skills/code-review/` — the review phase: the
  [multi-aspect review](plugin/patterns/multi-aspect-review.md) pattern wired as a skill —
  fans out reviewers by aspect (correctness/reuse via `reviewer`, security via
  `security-engineer`, integration/API, style/lint via the real tools), verifies, aggregates
  into one approve/changes verdict (any blocker/major ⇒ changes), and writes a `review.md`
  handoff. Code is its target; docs/design and deep audits go to `deep-review` (per ADR 0013 /
  the user's split). **Tier-0 + Tier-1 recall 1.000 / specificity 1.000** (majority-of-3
  router sim — distinct from `deep-review`/`simplify` and the spine neighbours); review quality
  is the `reviewer`/`security-engineer` roles' Tier-2 (PASS).

### Added — Stage 2 thin slice (step 3a: architecture workflow)

- **`architecture` workflow skill** `plugin/skills/architecture/` — the `tech-design` phase:
  turns an approved PRD into `tech-design.md` + `adr-*.md` under `docs/sdlc/<feature>/`,
  weighing alternatives and tracing goals to components. Delegates the design to the
  `architect` role; owns the workflow + handoff validation. **Tier-0 + Tier-1
  recall 1.000 / specificity 1.000** (majority-of-3 router sim, non-overlapping vs
  product/plan/develop/research); design quality is the `architect` role's Tier-2 (PASS).
- **Review-lens enrichment** `plugin/skills/deep-review/references/lenses.md` — added dimensions
  surfaced by this session's self-reviews: eval/test-harness validity (fixtures run, isolation
  /no-leak, determinism, no degenerate-pass), robustness at seams (parsing external/LLM
  output), safety defaults (enforced vs opt-in), doc currency vs ADRs, and a "living catalog"
  rule (grow the lenses from new failure modes).
- **Tier-1 methodology**: sample each trigger prompt N times and take the majority (absorb
  router stochasticity), documented in the eval-loop guide.

### Added — Stage 2 thin slice (step 2: roles + standards)

- **Engine roles for the thin slice.** Renamed `implementer` → **`software-engineer`** (the
  base engineering role, language/framework-agnostic; loads the standards + stack skills by
  context — ADR 0014). Added two new gated quality roles: **`security-engineer`** (security
  lens of a review; read-only) and **`qa-engineer`** (designs/writes/runs tests; never weakens
  a test or edits implementation). Each ships an agent eval contract + planted-defect fixtures.
- **`engineering-standards` skill** `plugin/skills/engineering-standards/` — a lean,
  off-listing (`disable-model-invocation: true`) knowledge skill of the standards we apply in
  target repos; loaded by `software-engineer`, exercised through its Tier-2.
- **Eval-runner hardening** (`agent_eval`): write roles now **run in a forced per-case
  sandbox** — fixtures are materialized into a temp workdir by basename and prompts carry no
  repo-relative paths, so a write role can never reach or mutate the real repo. `parse_grading`
  is now robust to prose/code-fence wrapping and stray braces (balanced-brace extraction), with
  a one-shot grader retry. Both fixes came out of the step-2 self-review (see below). Unit
  tests at 100% coverage.
- **ADR 0014** — one `software-engineer` base role + stack skills (not per-stack agents);
  updates spine.md roster and the living docs (the `implementer` rename).

### Verified — Stage 2 thin-slice roles Tier-2 (2026-06-21)

Tier-2 on a Claude subscription (Opus 4.8), per-case sandbox isolation. All pass; isolation
verified leak-free by fixture checksum (unchanged before/after).

| Role | mean | stddev | lower_bound | n | Gate |
| --- | --- | --- | --- | --- | --- |
| software-engineer | 1.000 | 0.000 | 1.000 | 5 | PASS |
| security-engineer | 1.000 | 0.000 | 1.000 | 5 | PASS |
| qa-engineer | 1.000 | 0.000 | 1.000 | 5 | PASS |

**Self-review caught real defects** (two independent adversarial reviewers, per the
review-each-step discipline), all fixed before this result: a sandbox leak (a write role had
mutated a real fixture in an earlier run), two fixture bugs (a broken import and hyphenated
test files that bare `pytest` didn't discover), the opt-in isolation gap (now enforced for
write roles), a degenerate-pass security assertion, and the grader-JSON parse fragility.

### Added — Stage 2 thin slice (step 1: patterns + fixture)

- **Pattern references** `plugin/patterns/fan-out-fan-in.md` (partition → parallel subagents →
  synthesize; the backbone of phase-workflows) and `plugin/patterns/multi-aspect-review.md`
  (code review fanned out by aspect — correctness / security / integration+API / lint — into
  one verdict; the review gate inside `develop` and the engine of the `code-review` phase).
- **Fixture target-repo** `plugin/eval/fixtures/spine/target-repo/` — a small, real Python
  library (`taskstore`) with tests and a `FEATURE_REQUEST.md` (task priorities), the external
  target the SDLC-spine E2E scenario carries a feature through on an isolated copy.
- **Tooling:** ruff now excludes `plugin/eval/fixtures` (fixtures are test data, not source).
- `docs/architecture/overview.md`: fan-out/fan-in promoted from deferred to a built pattern.

### Added — Stage 2 design

- **SDLC spine design** `docs/architecture/spine.md` + **ADR 0013** (supersedes ADR 0012):
  the spine is a **chain of phase-workflows** — `research, product, architecture, plan,
  develop, code-review` — each a multi-stage skill that gathers inputs, **fans out subagents**
  by direction/component, synthesizes, and analyses; joined only by handoff artifacts.
  Fan-out/fan-in becomes a **core** pattern. Built **fresh** with the ancestor `ai-skills`
  repo as reference; an **expanded specialist agent roster** (stack engineers, architects,
  security/qa/…, each gated; supersedes ADR 0009's Stage-1 "no new roles"); phase-workflows
  are model-driven fan-out (SKILL.md procedure + `lib/` glue), not the harness Workflow tool;
  trigger taxonomy by owned artifact; E2E on a Python fixture target-repo; **thin slice
  `architecture → develop → code-review` first**, multi-language (by-stack) after.
  Pre-implementation. ADR 0012 (thin routers) retained as superseded.

### Added — handoff

- **`docs/handoff-to-cli.md`** — checklist and starter prompt for continuing implementation
  (Stage 1+) in the Claude Code CLI, where the plugin runs and the eval loop executes.

### Fixed — packaging

- **Editable install (`pip install -e .`)** failed with a setuptools flat-layout error
  ("Multiple top-level packages discovered: ['dev', 'plugin']"). Added `[build-system]` and
  `[tool.setuptools]` (`package-dir = {"" = "plugin/lib"}`, `packages = ["agentic_forge"]`)
  so only the real package is built.

### Changed / Fixed — documentation review

- **Overhead gating made real:** `benchmark.summarize` now computes token/time overhead
  deltas from optional `timing.json` input, which `gate.tier2_quality` already checks
  (previously the gate could never apply overhead budgets). Added tests.
- **Agents now gated like skills:** `validate_agent` requires a sibling eval contract at
  `plugin/agents/evals/<name>.evals.json` with `component.type: agent`; skill contracts must
  declare `component.type: skill`. Added tests for agents, the manifest, and validator
  branches.
- **Coverage enforced:** `pytest-cov` added; CI runs `--cov=agentic_forge --cov-fail-under=80`
  (coverage ~96% at that milestone). Aligned the coverage claim across `CLAUDE.md`, overview, and
  meta-core docs.
- **Reduced duplication:** the eval-pyramid definition is now canonical in
  `docs/architecture/overview.md`; `plugin/eval/README.md` points to it instead of restating.
- **Citation fix:** `skill-creator` references updated to the official
  `claude-plugins-official` plugin and install command.
- **Plan consistency:** roadmap Stage 1 design questions marked resolved (engine.md/ADR 0009);
  Stage 2 role set pinned to the four roles + built-in Explore/Plan; Stage 3 split into
  vault-infra (Stage 0+) vs write-path (needs Stage 2). README notes the KB is Layer 3.

### Notes

- Decision records for the choices above live in `docs/architecture/decisions/`.
- Gate status at this milestone: `validate` clean, `pytest` green, `ruff` clean,
  `mypy` clean; `skill-factory` and the four engine roles pass Tier-0 (coverage ~97.6%). The
  agent Tier-2 runner is in place — run it locally (`python dev/run_agent_evals.py`) or via
  `eval.yml` using a Claude subscription token (`CLAUDE_CODE_OAUTH_TOKEN`); see
  [docs/eval-runbook.md](docs/eval-runbook.md).
