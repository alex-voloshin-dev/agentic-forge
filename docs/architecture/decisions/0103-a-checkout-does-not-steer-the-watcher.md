# ADR 0103 — A checkout does not steer the PR watcher

Status: Accepted (implemented)
Date: 2026-11-03

Corrects [0067](0067-deep-review-remediation.md) §3: settings read before the checkout were not out of a
PR's reach. Amends [0068](0068-pr-watch-autostart.md) (where the queue is read) and
[0072](0072-shipped-cli-and-user-level-state.md) / [0080](0080-state-migration-and-the-rolling-window.md)
(the read fallback and the migration of two files). Applies the rule of
[0100](0100-external-reviewer-isolation-and-skip-reasons.md) and [0102](0102-a-checkout-does-not-choose-where-state-goes.md)
to a third group of settings.

## Context

The scheduled watcher pushes and merges with the operator's `gh` credentials. Four things let a repository
direct it. All four were reproduced: the first three with a fake `gh` that logs its argv, the fourth with the
real `claude` CLI. Real GitHub was not exercised.

**The repo's config controlled it.** `settings.resolve` merged the repo file over the user file, so a committed
file could set `pr_watcher.enabled`, `auto_merge` and `repos`, even over a user-level `enabled: false`. The merge
gate has no approval requirement, and `repos` names any slug the operator's token reaches. So a checkout on the
operator's scheduler could cause merges, in repositories other than itself.

**The trust boundary did not hold.** ADR 0067 resolved settings before each `gh pr checkout`, but nothing put
HEAD back. So the second pass in a tick, and every pass on the next tick, read the previous PR's tree as trusted.
A fork's tree was on disk for this: `bin/pr_watch.py` refused a fork only after the driver had checked it out, so
a stranger's PR could turn off an operator's `auto_merge: false` for the same-repo PRs after it.

**Legacy files stayed authoritative.** A regular file committed at `.agentic-forge/pr-watch-queue.json` was read
by the drain, imported by the `pr_created` hook and promoted by `state_migrate`. One at
`.agentic-forge/schedule-state.json` with timestamps in the future stopped every job. ADR 0102 closed the symlink
at those names and left the regular file as a named residual risk.

**A PR's tree configured the fixer's session.** The fixer ran `claude -p` in the PR's tree with `--setting-sources
project`, the evals' setting. So the tree's `.claude/settings.json` ran hooks as the operator, before any model call,
on any unresolved thread, and with no credentials configured. "No Bash" limits the model, not the harness.

## Decision

**1. `pr_watcher` is the operator's.** `_drop_repo_watcher_settings` removes the repo file's whole section before
the merge, as `_drop_repo_reviewer_settings` does, so no later path can read it. That is `bot`, `max_threads`,
`repos`, `trusted_reviewers`, `auto_merge`, `auto_watch`, `max_ticks`, `merge_method`, `poll_seconds`, and any key added
later. A repo may only switch things off: `enabled: false`, `auto_merge: false` and `auto_watch: false` are honoured
downward, because a repo may stop automation on itself, and each wins over the user-level value and is reported. A repo value
cannot turn anything on, narrow `auto_merge` to a list, or add a repo. A value that differs from the one in effect gets a warning naming the key and not the value; one
that equals it gets none, because the shipped example has them all.

A repo file that was dropped keeps what it clearly switches off, from the raw text if it will not decode, as the
reviewer's does. The malformed-config fallback restores the user-level section, so a repo file cannot reset it
either, and applies what a repo switches off. It keeps only scalars and lists of strings, because that path must not raise.

**2. Per-repo merging: `auto_merge` also takes a list, and there is no new key.** `docs/configuration.md` told people
to turn merging on per repo, and that use is legitimate, so it has to survive. `auto_merge: ["owner/name"]` merges
only in those repos; `true` still means every repo the operator's scheduler runs on. `Settings.merges_in(slug)` is
what to ask, and it is case-insensitive as GitHub is.

`repos` plus a user-level `auto_merge: true` does not already express this, which was the first thing checked:

- `repos` drives only the hourly sweep. The queue drain runs in any checkout the clock runs in, and does not read
  it to decide on a merge, so `auto_merge: true` with `repos: ["me/a"]` still merges a queued PR in `me/b`.
- Scoping `auto_merge` to `repos` would make merging in a repo also mean sweeping it. The sweep watches **every**
  open same-repo PR in it, which ADR 0068 rejected as the default. With a gate that wants no approval, that turns
  "merge what I queue here" into "merge anything green here".

**3. Each pass has a worktree of its own, and the operator's tree is not involved.** In `run_scheduled`:

- **Settings are read once**, by the job, before any PR's tree exists, and passed to `_watch_one_pr`.
- **The fork check comes first**, before any fetch. What `bin/pr_watch.py` does for a fork is print one line and return,
  so nothing needs its tree. An answer that does not say is not "not a fork": `pr_watch.parse_head` raises, and the
  pass fails. It also gives the head commit, `headRefOid`, added to `PR_QUERY`. The check in `bin/pr_watch.py` stays,
  for a manual `--apply`.
- **The tree.** `git fetch origin -- refs/pull/N/head`, with `--no-write-fetch-head --no-tags --no-recurse-submodules`,
  so no ref of the operator's and no `FETCH_HEAD` changes, and `GIT_LFS_SKIP_SMUDGE=1`, as a smudge would download what the PR's
  pointers name. Then `git worktree add --detach <dir> <oid>`, with `<dir>` a
  fresh directory under `user_state_root()/pr-watch-passes/`. That is user-level even under `state.in_repo`, so the tree
  is never inside a repo, and `.agentic-forge/` of the operator's cannot reach `git add -A`. Git calls here disable
  hooks. This works with the branch checked out in the operator's tree, since the worktree holds no branch, and with the
  clock in a linked worktree. A commit that the fetch did not bring means the head moved, and the next poll sees it.
- **The child runs there.** The fixer commits on the detached HEAD and pushes `HEAD:refs/heads/<branch>`. A `finally`
  does `git worktree remove --force`. A failure there is recorded and is not fatal, as nothing of the operator's is
  involved.
- **A killed add.** A `git worktree add` that was killed leaves a record locked as `initializing`, which one `--force` refuses and
  `prune` skips, so a repo always hitting the timeout would gain one per pass. `remove --force --force` is used under the passes
  directory, and a failure is reported.
- **The log stays with the operator.** `main_repo_root` recognises `<main>/.git/worktrees/<n>` and nothing else. So under a clock in a
  submodule, or with `--separate-git-dir`, a pass's tree does not lead back, and each pass leaked a state directory, lost the audit
  trail, and under `state.in_repo` pushed the log to the PR. The driver passes `--state-repo`, the operator's checkout, and every
  `diagnostics.emit` in the child uses it. `main_repo_root` is not widened: it does not trust a pointer further than that, and should
  not start for this. If the clock's own root has no `.git`, the pass is refused and that is recorded.
- **A path need not be UTF-8.** `_git` decodes with `surrogateescape`, as one such worktree in `git worktree list` used to stop every
  job with a traceback.
- **Models are the operator's on a scheduled pass.** The driver resolves `models` with `repo_file=False`, since a clock the old driver
  left on a PR's branch would otherwise take them from that tree. Upgrading: put the clock's checkout back on its branch, as that tree's
  `enabled: false` also stops the watcher.
- **The child does not read the tree's config.** `pr_watch.py --from-scheduler` calls `settings.resolve(repo,
  repo_file=False)`, which does not open the repo's file. The driver gives it the operator's `models` entry as `--model`.
  `diagnostics.state_root` does not open it either, since `state.in_repo` is user-level already.

**4. Runs are kept apart by a lock the watcher inherits.** A pass may take 1800 s on a 10-minute clock. A run holds `flock`
on the main checkout's directory, since linked worktrees share a state root, and each watcher inherits the descriptor
through `pass_fds`. Otherwise a killed driver would free the lock while its child still worked, and the next run would
clean up the tree in use. No file is created, and the kernel releases it when the last holder dies. A held lock exits 0.
After 6 polls in a row it is an anomaly and shows in `--health`, because a stalled watcher otherwise looks like a quiet
one. With the lock held, a run first removes what killed runs left under the passes directory.

They are removed by name rather than with `git worktree prune`, which would also drop the record of an operator's own
worktree on a disk that is not mounted right now. The child's `claude` and `gh` do not inherit the lock: if the child alone
is killed while its fixer runs, that session has lost its way to push, and its directory can go.

**5. The merge is pinned.** `merge_argv` requires `head_commit` and passes `--match-head-commit`, from the same read the
gate used. So a push after that read fails the merge rather than riding through on the earlier green checks. What is not
a commit id raises, and `run_watch` reports the merge as not done.

**6. The fixer is confined, by the CLI's own flags.** `claude_cli_runner` gains `setting_sources`, `strict_mcp_config`, `tools`,
`permission_mode`, `session_persistence`, `denials_undetermined` and `settings`, and `pr_watch._FIXER_SESSION` with
`_fixer_settings()` is what the fixer passes, on a manual `--apply` too:

```
claude -p ... --setting-sources "" --strict-mcp-config --tools Read,Write,Edit,Grep,Glob
       --permission-mode acceptEdits --no-session-persistence
```

Evals keep `--setting-sources project --allowedTools ...`, as a project's settings are part of the repo under test. The first
version of this decision used `--setting-sources user --allowedTools ...`, and a review broke it: `--allowedTools` only grants,
so Bash stayed in the session, and a user-level `allow: ["Bash(*)"]` or `defaultMode: bypassPermissions` let a
prompt-injected fixer run commands with `GH_TOKEN` in reach. And allowed by name, `Read` and `Write` reached anything the
operator could: `~/.config/gh/hosts.yml`, `~/.agentic-forge/config.json`, a `.pth` under `site-packages`, `~/.ssh/authorized_keys`,
the operator's checkout. That second part was older than this branch.

Measured with the real CLI (2.1.317), with a local stub scripting the model's tool calls, an empty or hostile `HOME`, and a tree
carrying hooks, `env`, `apiKeyHelper`, `.mcp.json`, memory files, rules, agents, skills and commands. `tests/test_fixer_real_cli.py`
pins this table, with the evals' flags as its control:

| | Evals' flags | Fixer's flags |
|---|---|---|
| Tree's hooks | run, with `GH_TOKEN` in their environment | do not run |
| `.mcp.json` server | spawned | not spawned |
| `apiKeyHelper` | run, its output sent as the API key | not run |
| Tree's `env` | `ANTHROPIC_BASE_URL` moved the API to the tree's address | not applied |
| `CLAUDE.md`, `.claude/` rules, agents, skills, commands | in the request | not in the request |
| A `CLAUDE.md`, rules or a skill in a subdirectory, on a `Read` below it | | not in the request |
| `Bash`, `WebFetch`, `Agent`, `Skill` | offered | do not exist |
| `Read`, `Write`, `Grep`, `Glob` outside the tree | | denied |
| The CLI's own memory: `~/.claude/projects/<main-checkout-slug>/memory/`, `~/.claude/agent-memory/` | | index out of the request; every call denied |
| `Read` or `Write` through a symlink in the tree that leads out | | denied |
| `Write` to `.git/config`, or to a worktree's `.git` file | | denied |
| `Edit` and `Write` in the tree | | work |
| User settings `allow: ["Bash(*)"]`, `defaultMode: bypassPermissions` | | no effect |
| User settings `defaultMode: plan` | | no effect: the fixer is not stopped |
| A user-level `PreToolUse` or `SessionStart` hook | | does not run |
| A plugin installed at user level, its hook and the vault titles it brings | loaded under `user` | not loaded, not in the request |
| A transcript under `~/.claude/projects/` | written | not written (the empty directory is still made) |

The memory row needs its own flag. The CLI exempts those two directories from the working-tree limit, with no `permission_denials`,
so with the flags above alone a real run read `memory/creds.md` and committed the content to the PR, and edited `MEMORY.md` so the
operator's next session, which has Bash, carried the injected line. The fixer therefore also passes `--settings
'{"autoMemoryEnabled":false,"permissions":{"deny":["Read(~/.claude/**)","Edit(~/.claude/**)"]}}'`, plus the same
rules for `CLAUDE_CONFIG_DIR` when it is set, normalised as the CLI's exemption is. A value holding a character special to rule syntax gets
no session, since the rule would match nothing while the CLI still exempted the real directory. There is no `Write(...)` rule: the CLI warns
on every session that only `Edit(path)` rules match file edits, and the tests show `Edit` covers `Write`. The test uses the MAIN checkout's
slug, as a made-up one hid this, and has a control without the settings.

The CLI also exempts reads under `<tmp>/claude-<uid>/<cwd-slug>/`, which holds the output of the operator's other sessions in the same
directory. A scheduled pass's tree has a slug of its own, but on a manual `--apply` a token read from there reached the PR's branch. So each
session gets a fresh, empty `CLAUDE_CODE_TMPDIR`, removed afterwards, and that too is pinned on a real run.

An in-tree edit and a denied read of `../out/secret.txt` were also confirmed by the maintainer on a real OAuth login with a real
short session.

What stays, and what the fixer's flags do not do, is under residual risks.

**6a. What the session did decides what is posted.**

- A denied tool call is `permission_denials` in the CLI's JSON envelope, and with `denials_undetermined` the thread reads as
  undetermined. A session that was refused a read and then says "no change needed" did not decide that, and the canned "No change
  made" must not reach the reviewer.
- A thread left undetermined fails the job, so a session that never ran is not a pass with health ok. That covers an operator who
  authenticated through an `env` in `settings.json`, committed or user-level, which is no longer read: it must be in the clock's
  own environment, or in the CLI's login.
- **Fixes are pushed before anything says so.** `run_watch` used to reply "Addressed in <sha>" and resolve the thread, then push. A
  refused push then destroyed the commit along with the worktree, after GitHub had been told. Now it pushes, then replies and
  resolves. A refused push posts nothing, and the thread reads as undetermined.
- **Only threads from people who can already write, or from listed reviewer apps, go to the fixer.** For a person there are two
  checks. `authorAssociation` must be `OWNER`, `MEMBER` or `COLLABORATOR`, as a cheap first filter, and then `GET
  /repos/{o}/{r}/collaborators/{login}/permission` must say write, maintain or admin, asked once a pass per login and failing closed.
  The association alone is too broad: `COLLABORATOR` has no role attached and `MEMBER` is organisation-wide, so someone without write
  access could have had a commit pushed under the operator's name. Reviewer apps are `Bot` with `NONE` or `CONTRIBUTOR` in real public data,
  and ADR 0063 built the watcher for them, so an operator lists them in the user-level `pr_watcher.trusted_reviewers`. An entry counts
  only for an author whose `__typename` is `Bot`, as GraphQL drops the `[bot]` suffix and a person could register the bare login. An
  untrusted thread reaches no session and gets no reply, and it still holds the merge gate, and only a person can resolve it, so a stranger
  can neither instruct the fixer nor clear the gate. The check is on a thread's first comment, as that is what the fixer is given. A PR that
  runs out of ticks with a thread still held shows in `--health`, since it never got its answer. The query fields were read for real:
  `authorAssociation` is `CommentAuthorAssociation!`, and the permission endpoint answers `admin` for this repo's owner and `read` for a
  stranger.
- **Git's own answers count.** `git add`, the staged listing and `git commit` are checked, and HEAD must have moved. A signer or an
  identity the clock lacks used to get "Addressed in <old head>" and a resolved thread, and the next poll merged without the fix. A failure
  discards the tree and reads as undetermined, with the tail of git's complaint.
- **A session cannot change what acts elsewhere.** After the session and before the commit, the staged paths are listed with
  `--no-renames`, so moving a file out of one still counts. Any component in `.github`, `.gitattributes`, `.gitmodules`, `.husky` or
  `.agentic-forge`, `.claude` or `.mcp.json`, in any case, refuses the commit: the thread reads as undetermined, and nothing claims a
  fix. `git ls-files -s` is read first: a tree where one of those names is itself a symlink gets no session, as `.github -> cfg` and a write
  to `cfg/workflows/x.yml` would otherwise read as touching none of them. A link merely below one, such as
  `.github/copilot-instructions.md -> ../README`, does not stop the session. Its in-tree target is protected instead, at the commit, so with
  `.github/workflows/ci.yml -> ../../ci/ci.yml` a change to `ci/ci.yml` is refused and the link is named. A manual `--apply` on a dirty checkout starts no session, so a
  rejection cannot reset the user's staging, and nothing of theirs goes into a fix commit.
- **A PR that is no longer open gets nothing.** `run_watch` stops when `state` is not `OPEN`, so a merged PR's deleted branch is not
  recreated by a push.
- **The gate reads `latestOpinionatedReviews(first:100)`.** A `hasNextPage`, or a change request with no author, keeps it shut. The field
  was read for real on this repo and on a public one.

**7. A PR outside `origin` gets no fix pass.** The fixer pushes to `origin`, so a PR in another repo would be fixed from the
wrong tree and pushed to the wrong place. It gets no tree: the child runs with `--merge-only`, where threads go
undetermined with nothing posted, and exits 1 with a recorded reason if there was work to refuse. A merge goes by slug and
may stand. It is not fixed by pushing to another URL, which would make a commit in one repository's tree for another.

**8. A failed pass fails its job in the sweep too.** `_run_pr_watch_live` counts failed `WatchOutcome`s and raises as the
queue drain does. A refused pass used to read as a watched PR, and `--health` as ok.

**9. The queue and the job state come from the state root only.** `diagnostics.current_state_file` has no fallback, and
the drain, the `pr_created` hook and `schedule.load_state` use it. `state_migrate` does not import either file: it names
and removes them, and says when one was tracked, since that shows as a deletion to commit. The session-start notice, the
hook's notice and the scheduler's output name what was ignored, from a fixed list and never a directory listing.

A queue entry naming a repo that is neither the checkout's `origin` nor in the user-level `repos` is dropped with a
recorded reason, before any `gh` call. It is dropped rather than kept, because keeping it would repeat the anomaly
every ten minutes for a day. `origin` lives in `.git/config`, which a commit cannot change. No origin matches nothing.
`--health` shows such drops for a week. **A renamed repo reads exactly like this**: GitHub redirects the old name, so the clone keeps
working, while `gh pr create` prints the new one, and that entry is dropped until the `origin` remote is updated.

The state root is keyed by path, so a queue drains in the checkout that created the PR or a linked worktree of it. A clock
in a different clone says so when it finds entries for its repo under another checkout's state.

## Why the first design was dropped

This ADR first kept `gh pr checkout` in the operator's tree: refuse a dirty tree, record the ref in a marker file, restore
it in a `finally` with `git checkout --force` and `git clean`, and recover from the marker on the next run. A review
reproduced each of these against it:

- `status.showUntrackedFiles=no` hid untracked work from the dirty check, and `git clean` then deleted it, with exit 0.
- Edits the operator made during a pass were destroyed by the restore. The lock kept out other scheduled runs and nobody else.
- A killed driver freed the lock while its child worked, so the next run moved the tree, and the fixer committed onto the
  operator's `main`.
- Untracked files the check exempted under `.agentic-forge/` were swept up by `git add -A`, committed, pushed, then deleted
  locally. A marker pushed that way, under `state.in_repo`, broke later checkouts.
- A marker committed under `state.in_repo` moved HEAD to the ref it named.
- A stale marker stopped every job, including ones that had nothing to do with a PR.
- A tag with the branch's name restored to a detached HEAD.
- Recovery moved an operator who had moved on since the kill.

Every one comes from sharing the operator's tree, so patching them one at a time would have been the same shape as a command
parser. All that machinery is gone. The first version's reason for rejecting a worktree per pass was that it could not be
validated here against real GitHub, and that applied equally to what was chosen instead.

The same design told operators to give the clock a dedicated clone. That silently stopped auto-watch, as the state root is
keyed by path. With no tree shared, the advice is gone.

## Rejected alternatives

**`git worktree prune` for leftovers.** See decision 4.

**Reading settings once for the whole run in `main`.** Tests and jobs call the actions directly, and a value threaded
through `_ACTIONS` would change every action's signature for two of them. The operator's tree does not change during a
run, so the second job reads the same thing.

**A new `pr_watcher.merge_repos` key.** A key that means nothing without another key, in a section where one
key already says whether to merge.

**Keeping the fallback for the two files until a state file exists.** That is exactly the window the defect used, on
any fresh install.

## Residual risks

- **What a fixer session can still reach.** Before this ADR: anything the operator's account could, by `Read` and `Write`, and whatever
  the tree's settings chose to run. After: the tree it works in, through five tools, and what the CLI exempts from that limit and this ADR has
  not closed. Its memory is off and denied by name, and its temp directory is a fresh one; a directory the CLI starts exempting in a later
  version would not be. `CLAUDE_CODE_REMOTE_MEMORY_DIR` and `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE`, if the operator's environment sets them, move
  the memory to where these rules do not look. It can write anything in that tree that is not a
  protected path, and that is pushed to the PR's branch under the operator's name, so a prompt-injected session from a trusted thread can
  still change the PR. A second reader in CI is what catches that. It needs the auto-merge gate's checks to re-run, and they do, since
  the same pass never merges.
- **What still reaches the model from the tree.** The CLI's automatic `gitStatus` block carries the tree's branch, status and recent commit
  subjects to the model before any tool call, and nothing in these flags removes it. A commit subject is therefore an instruction channel
  from anyone who can push to the branch, as is any file the model reads. The test pins that it arrives, so a change in the CLI is noticed.
- **What the session no longer has.** User-level settings are dropped too, deliberately: the operator's hooks do not run in it, and a
  plugin installed at user level does not load, so this plugin's own hooks and the vault titles they bring stay out, and the audit log has
  no record of the fixer's tool calls. Only the watcher's own record of what it did remains.
- **The confinement is the CLI's.** `Write`'s refusal of a symlink that leads out, and the rest of that table, are its behaviour, on 2.1.317.
  The plugin pins no CLI version, so a later one may differ, and `tests/test_fixer_real_cli.py` is what would notice, when it runs: it
  skips where the CLI is absent, and CI's Tier-0 has none.
- **A session's own record of a denial.** A denial reads as undetermined only through `permission_denials` in the envelope, so a CLI that
  stopped reporting it would turn this back into a "No change made".
- **Protected paths are a list.** `.github`, `.gitattributes`, `.gitmodules`, `.husky`, `.agentic-forge`, `.claude` and `.mcp.json`, not other
  hook managers or other CI systems. A fixer's change to those is pushed.
- **A same-repo PR's tree is still fixed and pushed.** A branch in the repo needs write access, which the watcher treats as
  trust: ADR 0044 scopes auto-apply to that.
- **The merge gate still has no approval requirement.** With `auto_merge` on, a green same-repo PR merges. That is ADR
  0063's design, and this ADR only decides who may turn it on.
- **`state.in_repo: true` puts the queue and job state back in the tree.** There a committed file at those names is the
  state root, and it is read. The origin check still applies. It is the operator's choice, and it applies to every repo
  they open.
- **`bin/pr_watch.py` needs `jsonschema`.** It imports `agent_eval`, which imports `evals`, which imports it at the top
  level. So without it the child exits 1 at import: recorded, nothing merged. Older than this; a scenario pins it.
- **A repo's `false` opt-out is what the clock's own checkout says now.** The file is read from that tree, on its current commit. So it covers
  everything that clock watches, including other repos it is told to, it does not bind a repo merged by slug, whose own file is not read, and
  a commit not yet pulled does not count.
- **A link to `.git` in an ordinary clone.** On a manual `--apply`, a symlink `gg -> .git` lets `Read` reach `gg/config` (writes are denied), so a
  token embedded in the origin URL could be committed. A pass's worktree is not affected, as its `.git` is a file with nothing to read.
- **What write access does not prove.** The check says a person may push to the repo, which is the same reach the fixer has, and no more.
  It reads a thread's first comment only, so a thread from such a person that quotes a stranger's text still goes to the fixer. The answer
  is cached for one pass, so a permission removed mid-pass applies to the next.
- **A reviewer app is trusted by its login and its type.** `trusted_reviewers` is the operator's statement that this app's comments may
  drive a fix. Listing one means its output, which may itself quote a PR, is instructions.
- **`pr_watcher.bot` still compares a login as written.** Its default, `github-actions[bot]`, is not what GraphQL returns (`github-actions`), so
  that app's threads count as open, and without `trusted_reviewers` hold the gate. Older than this ADR, and left alone.
- **Warnings print once per process.** The `Settings.warnings` a session sees are unchanged.
- **An `origin` that `connectors.slug_from_remote_url` does not read names no repo.** It is strict about the host, so an SSH
  host alias (`git@work-github:me/mine.git`) drops that checkout's queue entries, and a repo listed in `repos` gets merges
  only, with a recorded refusal for anything needing a fix. Failing closed was chosen over a second, looser parser of the
  same URL.
- **The fetch needs git credentials the clock can use.** `gh pr checkout` brought its own through `gh`. The fixer's push
  always needed them, so this adds a requirement only for a watcher that never pushed.
- **The first run after an upgrade.** With the job state gone from the repo, a checkout that had one at the legacy path sees
  every job as due once.
- **Windows has no `flock`**, so runs are not kept apart there, and a second run could remove a first run's worktree.
- **Everything about GitHub itself is unverified.** See the runbook's list: `refs/pull/N/head`, `--match-head-commit`,
  `headRefOid`, and that `gh pr merge -R` does no local work.

## Consequences

- Behaviour change: a repo's `pr_watcher` values are ignored, except that it can set `enabled`, `auto_merge` or `auto_watch` to `false`. An
  operator who relied on one
  sets it in `~/.agentic-forge/config.json`. The shipped example's `repos` is now `[]`, since it is also meant to be
  copied into a repo.
- Behaviour change: a queued PR or job history at the legacy path is not carried over. A PR is queued again by the next
  `gh pr create`, or listed in `repos`.
- Behaviour change: a PR in `repos` that is not the checkout's `origin` gets merges only, and a pass that had work to refuse
  fails its job.
- `merge_argv` requires `head_commit`, and `push_argv` gives a full ref.
- Behaviour change: authentication through a committed or user-level `settings.json` `env` no longer reaches the fixer, whose session then
  never runs, which now fails the job. Use the CLI's login, or the clock's environment.
- Behaviour change: review threads from anyone without a standing in the repo are not fixed. They hold the gate until someone resolves them.
- `tests/test_pr_watcher_trust.py` runs all of this as real `run_scheduled.py` and `pr_watch.py` processes over a real git
  repository and a real bare origin, with a fake `gh` and `claude`. `tests/test_fixer_real_cli.py` measures the fixer's
  arguments against the real CLI. `tests/test_settings.py` holds the resolver's table, with and without `jsonschema`.
