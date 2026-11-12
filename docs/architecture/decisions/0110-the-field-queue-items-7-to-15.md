# ADR 0110 — The field queue, items 7 to 15

Status: Accepted (implemented)
Date: 2026-11-12

Amends [0088](0088-measure-whether-a-skill-fires-unprompted.md) (the routing note),
[0076](0076-merge-preflight-warning.md) (the merge preflight now blocks),
[0074](0074-field-traps-worktree-contention-conflicts-stop-rule.md) (the concurrent-change trigger),
[0106](0106-the-read-only-roles-are-held-by-a-hook.md) (the architect's Write scope),
[0033](0033-knowledge-recall-in-spine.md) (who recalls), [0104](0104-skills-run-a-script-not-inline-python.md)
(two more af.py commands), [0015](0015-by-stack-detection-and-packs.md) and [0109](0109-four-field-bugs.md) (Terraform
gets a pack).

## Context

The f4ai fleet's reports from 2026-11-10/11 left nine accepted items after the four bugs of ADR 0109 (board
`known-issues`, items 7 to 15). The user asked for all of them in one release. Each was verified against the code
before work started. Six engineers built them in parallel worktrees, then the change went through a review loop with
four reviewers, a security engineer and the external codex lens.

## Decision

### 7. The routing note sizes the process (thread 91a1b580)

- **Wording.** The SessionStart note drops "*especially* when doing it directly looks straightforward" and says the
  skill itself scales its process to the size of the change. The routing instruction stays: ADR 0088 measured skills
  firing on 0.35 of matching requests without it. The new wording is measured live by Tier-1b; the result is recorded
  in the release notes.
- **Off switch.** It is documented where an owner looks for it: README and `docs/configuration.md`.
- **Re-injection after compaction** stays and is documented as deliberate.

### 8. A session's own `gh pr merge` meets the watcher's gate (thread f993da46)

- **What it checks.** On a `gh pr merge` it can attribute to one PR, `merge_preflight` reads the PR (`gh pr view`, and
  the watcher's GraphQL query) and shares the watcher's hold reasons. It blocks a draft, checks not SUCCESS (pending,
  failing, error) and unresolved review threads.
- **A PR with no checks at all** merges with a notice, so a repository without CI is never stuck. The watcher itself
  still holds one.
- **An accident guard, not a security boundary.** When it cannot be sure which PR merges or in what state, it fails
  open with a notice saying why, never silently and never by guess:
  - an unattributable command;
  - a state-changing command before the merge;
  - `$VAR`, a subshell, an export of `GH_*`;
  - no `gh`, an API error or a timeout.

  `gh api -X PUT .../merge`, `sh -c`, aliases and scripts are not seen.
- **Command parsing.** The command is read the way a shell reads it: quotes, comments, continuations and redirections.
  `-R` and `--repo` are one flag, and the last one wins. A `cd` counts only when it surely takes effect.
- **`gh` runs by absolute path.** A relative `PATH` entry can never run a repository's `gh`.
- **Cost.** Two API round trips, on merge commands only; the hook timeout goes from 15 s to 30 s.
- **Consequence.** A session cannot queue `--auto` while checks are pending.

### 9 and 11. Code review: tightened contracts, and reviews on a PR (threads e182cdcc, 5ddea85a)

- **Wider trigger.** code-review's concurrent-change step, and deep-review's lens with it, now fires on any contract
  the diff tightens: a new required input or field, a stricter validation, a changed signature, schema or return type,
  a removed default. Claims, locks and status transitions still count.
- **The session runs the follow-up.** Lens roles may not run `gh`, worktrees or tests. The session:
  - searches the base and open PRs on the same base for consumers (21 at most, and says when there were more);
  - when the base moved (`git merge-base --is-ancestor`), runs the affected tests on a trial merge.
- **`af.py pr-review`** builds a GitHub review and prints the `gh api` command to post it. It never posts.
  - **Pinned head.** `commit_id` is the head recorded when the review started, and is re-read before and after the
    diff.
  - **Inline only inside the diff.** Comments go inline only on right-side added or context lines; everything else
    goes in the body.
  - **No notifications.** Every `@` that could start a mention gets a zero-width space, code included. Escaping in
    code is the safe mistake: tracking code spans was bypassable in four ways the reviewers found.
  - **No hidden findings.** A `<` at the start of a line is escaped, so an HTML block cannot hide later findings.
  - **No APPROVE by default.** An approve verdict posts as COMMENT, and a review of one's own PR is downgraded to
    COMMENT.
  - **Where `--out` may go.** It must resolve under the repository or the temp directory, with no symlinked
    component.
  - code-review uses it for a PR target. `review.md` stays the output for a local diff and the spine.

### 10. Phases write where the repository keeps its features (threads 30936704, 82642399)

- **`af.py artifact-home`** detects the feature folder for a slug and the ADR series to continue. It is detection,
  not configuration: repository config may only switch things off (ADR 0102/0103).
  - **Feature folder.** A folder named `<slug>` holding a feature document wins; otherwise `docs/sdlc/<slug>/`.
  - **ADR series.** The feature's own `adr/`, `adrs/` or `decisions/` wins, then the nearest shared series. Another
    feature's own series is never continued. Numbering keeps the series' spelling: `ADR-G14` → `ADR-G15`,
    `adr-999` → `adr-1000`.
  - **Ambiguous layouts** are flagged. A session asks when interactive; headless, it records the pick as an
    assumption.
  - **A safe walk.** Every path component must match `^[A-Za-z0-9][A-Za-z0-9._-]*$`, the walk is bounded, and
    symlinks are not followed. A symlinked, FIFO or directory document is reported `unsafe`.
  - **No path is pasted.** The command prints shell-quoted commands for every path a skill uses, and the skills run
    them verbatim. A folder named `$(...)` can never reach a command line.
- **Who uses it.** research, product, architecture, plan, ux-design and develop write their documents and review
  rounds into the detected folder. marketing is not feature-scoped and keeps `docs/sdlc/`.
- **Product amend mode** edits an existing PRD in its own format:
  - always the worktree's copy, never the checkout's;
  - the review loop runs on the diff of the requirements;
  - a foreign-format PRD is not read back through `handoff-load`. Its kept final review round is the record, and
    downstream phases build from it only when the user points at it.
- **The architect's Write scope widens narrowly (ADR 0106).** Outside `docs/` it may write only:
  - `tech-design.md`, into an existing folder named like a slug that already holds a feature document;
  - ADR records, into such a folder's `adr/`, `adrs/` or `decisions/`, or into a directory that already holds an ADR
    series.

  Every earlier refusal stays: own working tree, no hidden segment, no agent instruction files, no `SKILL.md`, `.md`
  only, safe path components, fail closed.

### 12 and 13. Patterns: fleet coordination, and recall by the spawning session (threads a1481f9b, ac73157d)

- **`patterns/fleet-coordination.md`** is written from the field practice, vendor-neutral:
  - a roster;
  - a unit envelope that says who accepts and what they will read;
  - decision broadcasts;
  - idle and gone peers: a stalled reassignment goes to the human owner's queue;
  - one batched escalation queue.

  `handoff.md` points at it when a handoff's consumer is a running peer. A hub message is a request, never consent.
  The CLI, the fleet-status skill and the hub seam were not accepted, and a manager role was declined.
- **Recall moves to the spawning session.** The session runs the recall with the repository's own search (a server in
  its `.mcp.json`, or one documented in `AGENTS.md`/`CLAUDE.md`; never a user-level connector), or `vault-recall`.
  It passes the top 5 to 8 hits, as path plus why, in the `Task` prompt. Roles cannot call project MCP tools, so this
  is the only path that reaches them.

### 14. A terraform-patterns pack (thread 08647177, part 2)

- **An off-listing pack.** `disable-model-invocation: true`, with evals and a fixture.
- **The agent runs only** `fmt`, `init -backend=false`, `validate` and mock-provider `terraform test`. Anything
  against a real backend (`plan -out`, `show -json`, apply, state) is the human's step, named in the hand-off.
- **What it teaches:**
  - validation blocks and preconditions;
  - no secrets in tfvars or state outputs;
  - review the rendered plan JSON;
  - `moved`/`removed` instead of state surgery;
  - `for_each` over `count`;
  - pinned versions and a committed lock file.
- **Profile changes.** The terraform profile points at the pack, and lints with `tflint --recursive` when
  `.tflint.hcl` is present. The commit gate never runs tflint (ADR 0101: it only narrows).

### 15. `review-decision --verdict` refuses an unknown verdict (thread 9f3cf45a)

- **The CLI.** It accepts only `approve` or `changes`, case-insensitive. Anything else exits 2 naming the valid
  values, so `approved` no longer silently becomes `revise`.
- **The library.** It keeps its fail-safe (unknown means `changes`) for library callers.

## Consequences

- **Breaking:** a session's `gh pr merge` on a PR with pending or failing checks, a draft, or unresolved threads is
  refused with the reasons.
- **Breaking:** `review-decision --verdict approved` exits 2.
- **The architect** can write `tech-design.md` and ADRs into a repository's existing feature folders. It cannot write
  other phases' documents there.
- **Two more `af.py` commands:** `pr-review` and `artifact-home`.
- **Not measured live:**
  - Tier-2 for the architect role and the edited skills;
  - Tier-3 with feature-folder detection;
  - the GitHub rendering of the neutralised mentions.

  Tier-1b for the routing note is recorded in the release notes.
