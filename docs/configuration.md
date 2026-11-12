# Configuration

The plugin reads optional JSON config from two places, both validated against
[`schemas/config.schema.json`](../plugin/schemas/config.schema.json):

- **User-level** (cross-project): `~/.agentic-forge/config.json` — your personal defaults (ADR 0049).
- **Per-repo** (committed): `<repo>/.agentic-forge/config.json` — project-specific overrides.

**Precedence (lowest → highest):** built-in defaults < user-level file < per-repo file < env vars.
The two files deep-merge, so a repo overrides only the keys it sets and inherits the rest. The reviewer
keys are the exception, for security: `external_reviewer.command`, `isolated`, `model` and `effort` are
**user-level only**, and a repo cannot turn on a user-level `external_reviewer.enabled: false`.
`state.in_repo` and `knowledge.allow_external_vault` are **user-level only** as well (ADR 0102), and so is
all of `pr_watcher`, except that a repo can switch off `enabled`, `auto_merge` and `auto_watch` (ADR 0103). All keys
are optional. A ready, schema-valid example with **every** key ships at
[`plugin/config.example.json`](../plugin/config.example.json) — copy it to either location and trim. In a
repo, those four reviewer keys, `state.in_repo`, `knowledge.allow_external_vault` and `pr_watcher` do nothing
(but for switching off `enabled`, `auto_merge` or `auto_watch`), so trim them there.

> These files are committed / home-local — **never** put secrets (API keys, tokens) in them. Use the
> env vars for secrets and one-off overrides.

## Keys

| Key | Type | Default | Effect |
|---|---|---|---|
| `logs.max_bytes` | int | `10485760` | Rotate the audit log past this size. The live log is a **bounded rolling window**: one active repo reaches the default in 11-15 days (field measurement: ~950 tool calls/day). Raise it to keep more in the live log; the rotated-out records are archived rather than lost (ADR 0080/0081). |
| `logs.keep_bytes` | int | `5242880` | Bytes of the newest records kept in the live log when rotating. |
| `logs.archives` | int | `6` | How many gzipped archives of rotated-out records to keep in `<state root>/archive/` (`audit-<timestamp>.jsonl.gz`), oldest pruned first. `0` restores the pre-2026.9.1 behaviour of discarding them. A rotation announces the span it moved **in days**, and where (ADR 0081). |
| `routing_note.enabled` | bool | `true` | The SessionStart note telling the session that agentic-forge skills are workflows to invoke (2026.9.3). Overridable with `AGENTIC_FORGE_ROUTING_NOTE` — the switch its own A/B uses (ADR 0092). |
| `pre_router.enabled` | bool | `false` | The deterministic pre-router hook (ADR 0089): on each prompt, name the clearly-matching skill in the prompt's context. Suggests only; never invokes. **Off by default** — measured at +0.095 activation over the session note (inside single-run noise) on a stand ADR 0090 then found empty, so the null result is uninterpretable; it stays off because the honest baseline left it nothing to fix (ADR 0091). Overridable with `AGENTIC_FORGE_PRE_ROUTER`. |
| `logs.enabled` | bool | `true` | Write a redacted audit record per tool call (ADR 0019/0078). **On by default** — it is the only record of what the agent did, and the substrate of the diagnostics bundle. Turning it off stops the writing; it does not move the file (that is ADR 0072's state root). Overridable with `AGENTIC_FORGE_LOGS`. |
| `diagnostics.enabled` | bool | `false` | Turn on the self-diagnostics log `~/.agentic-forge/state/<repo-slug>/diagnostics.jsonl` (ADR 0072) — guardrail denials, pipeline failures (ADR 0039). **This is "the logger."** Hook crashes are recorded regardless of this switch and announced once per session (ADR 0094); the file is rotated at session start under the `logs.*` bounds. |
| `state.in_repo` | bool | `false` | Keep generated runtime state (diagnostics, audit, schedule, PR-watch queue) **inside** the project at `<repo>/.agentic-forge/` instead of the user-level state root. Off by default: the plugin must not write into a repo it does not own (ADR 0072). **User-level only: set it in `~/.agentic-forge/config.json`, and it then applies to every repo.** A value in a repo file is ignored with a warning, in both directions, unless it equals the value in effect, because a checkout must not choose where the plugin writes (ADR 0102). See [State and symlinks](#state-and-symlinks). The committed `config.json` is unaffected — configuration is the project's, state is the runtime's. `AGENTIC_FORGE_STATE_HOME` relocates the root when the default is not wanted. |
| `knowledge.allow_external_vault` | bool | `false` | Read and write a knowledge vault whose directory resolves outside the repo (the nearest directory up holding a `.git` entry), for a vault you keep elsewhere and reach by a link. **User-level only: set it in `~/.agentic-forge/config.json`.** A value in a repo file is ignored with a warning, in both directions, unless it equals the value in effect, because a checkout can commit the link (ADR 0102). Only a real `true` counts. See [Vault notes and symlinks](#vault-notes-and-symlinks). |
| `subagent_budget.soft` | int ≥ 0 | `25` | Per-session subagent (`Task`) count at which the budget hook warns. |
| `subagent_budget.hard` | int ≥ 0 | `50` | Count at which the budget hook blocks further `Task` spawns. |
| `test_gate.skip` | bool | `false` | Skip the pre-commit test gate (the `commit_gate` hook). Read from `.agentic-forge/config.json` at the session's cwd, then the user-level file, as any key is: a file at the repo root does not reach a session standing in a package. **Set it in a separate call before the commit:** the hook runs before the command, so neither a file written nor a variable exported in the same call can reach it. See [What the test gate runs on](#what-the-test-gate-runs-on). |
| `review.passes` | int ≥ 1 | `3` | Calibrates the **scheduled non-convergence scan** (`diagnostics.scan_reviews`) — the iteration at which a still-`changes` loop is flagged. The in-skill loops use the constant `handoff.REVIEW_LOOP_BUDGET` (3) and do **not** read this; raising it above 3 only moves the detector's threshold (ADR 0067). |
| `external_reviewer.enabled` | bool | `true` | Enable the external reviewer pass — on by default, auto-invoked as an extra lens in every workflow that writes a reviewable deliverable: `develop` (`--kind code`), `product` (`--kind product`), `architecture` (`--kind technical`), `plan` (`--kind plan`), `research` (`--kind research`), `ux-design` (`--kind ux`), `marketing` (`--kind marketing`) (ADR 0042 / 0057 / 0060 / 0061 / 0062). Degrades gracefully when the CLI is absent; set `false` to opt out (e.g. secret-bearing repos). **This key is an exception to the precedence above:** a user-level `false` holds whatever a repo config says, and that attempt is ignored with a warning, because content goes to a third party (ADR 0100). A repo can turn it off, with a warning if that overrides a user-level `true`, and can turn it on if there is no user-level `false`. A repo's `false` survives its file being dropped when it can still be read there; see below. With it off, the skills' `review()` runs nothing and returns `None` (`disabled`). The operator's `--force` on `plugin/bin/external_review.py` still overrides it. |
| `external_reviewer.command` | string | `"codex"` | The reviewer executable name on PATH: a bare name, not a path or a shell line. **User-level only: set it in `~/.agentic-forge/config.json`.** A value in a repo file is ignored with a warning, because the operator chooses the program: a repo that chose it could have a program of its choosing run on your machine and forge the verdict (ADR 0100). There is no warning if it equals the value in effect, so copying the example into a repo stays quiet. At user level, anything but a bare name falls back to `codex` with a warning. The `--command` argument of `plugin/bin/external_review.py` is your own, so it may name a path, which is resolved against your current directory. The library's `review()`, which the skills call, runs only this configured value and refuses any other. |
| `external_reviewer.isolated` | bool | `false` | Run the reviewer without your user config and without persisting session files: codex `exec --ignore-user-config --ephemeral`, on top of the read-only sandbox (ADR 0100). Applies to the skills' calls as well as `plugin/bin/external_review.py`. Before each isolated run the plugin checks `codex exec --help` for both flags; if either is missing, or the check fails, the review **fails** (`isolation-unsupported`, CLI exit `3`), never run without them. This limits what the CLI loads from your home; it is not a stronger sandbox, and it does not change what is sent to the third party. **User-level only: set it in `~/.agentic-forge/config.json`.** A value in a repo file is ignored with a warning unless it equals the value in effect, because it would drop your whole `$CODEX_HOME/config.toml`, including provider or hardening settings (ADR 0100). **Recommended for repos that take outside contributions:** see below. |
| `external_reviewer.model` | string \| null | `null` | Passed as `--model`, isolated or not, only when set. Null leaves the choice to the CLI. **With `isolated` your configured model is not loaded, so set it here if you relied on it.** **User-level only**, like `isolated`: a repo must not choose the model that reviews it. |
| `external_reviewer.effort` | string \| null | `null` | Passed as `-c model_reasoning_effort="<value>"`, isolated or not, only when set. Whether codex honours this key has **not been verified** against a real run; it does not appear in `codex exec --help`. The same applies: with `isolated`, your configured effort is not loaded. **User-level only**, like `isolated`. |
| `models` | object | `{}` | Per-role / skill / `router` model tiers (ADR 0043) — each value is a tier (`default` / `simple` / `cheap`) or a model id. **Affects the eval/dev CLIs only** (`dev/run_*_evals.py`, `plugin/bin/pr_watch.py`, `dev/ralph.py`) — live-session role routing is the gate-validated agent frontmatter (ADR 0046), which this key does not change. Empty = the runner's default model everywhere. See the [eval runbook](eval-runbook.md). |
| `pr_watcher.enabled` | bool | `false` | Enable the PR watcher's outward GitHub writes (ADR 0044/0045). **User-level only: set it in `~/.agentic-forge/config.json`.** A repo file can only turn it off, with `false`, which wins over your `true` and is reported. See [the PR watcher and the checkout](#the-pr-watcher-and-the-checkout). |
| `pr_watcher.bot` | string | `"github-actions[bot]"` | The bot login whose review threads the watcher skips. **User-level only**, as is every key below in this section, except that a repo can set `auto_merge` or `auto_watch` to `false`. |
| `pr_watcher.max_threads` | int ≥ 1 | `10` | Max review threads handled per run. |
| `pr_watcher.trusted_reviewers` | string[] | `[]` | Logins of reviewer apps whose review threads may reach the fixer, such as `chatgpt-codex-connector` or `copilot-pull-request-reviewer`. An entry counts only for an author of type Bot (ADR 0103). |
| `pr_watcher.repos` | string[] | `[]` | `owner/name` repos the scheduled hourly job watches, every open same-repo PR in each. Also what lets a queued PR through when it names a repo other than the checkout's `origin` (ADR 0103). |
| `pr_watcher.auto_merge` | bool \| string[] | `false` | Let the watcher **merge** a PR once the merge gate opens (ADR 0063). Off by default — merging is irreversible and outward-facing. To turn it on per repo, list them: `["owner/name"]` merges only there and watches without merging elsewhere (ADR 0103). `true` is every repo your scheduler runs on. |
| `pr_watcher.merge_method` | `rebase`\|`squash`\|`merge` | `"rebase"` | How `auto_merge` merges. Reaches argv as `--<method>`, so it is an enum here **and** clamped in the library. |
| `pr_watcher.auto_watch` | bool | `true` | Let the PR-created hook **enqueue** a new PR for the scheduled watch (ADR 0068/0069). On by default — but it requires `enabled` as well, so with the watcher off the queue file is never created and the plugin writes nothing into your repo. Merging still needs `auto_merge` (off). **A 10-minute tick needs a 10-minute external clock** (`*/10 * * * * python plugin/bin/run_scheduled.py`): the plugin has no daemon. |
| `pr_watcher.max_ticks` | int ≥ 1 | `144` | How many drains one queued PR may consume before it is dropped (24 h at the 10-minute cadence). Nothing is watched forever. |
| `pr_watcher.poll_seconds` | int ≥ 60 | `600` | Autonomous re-check cadence (10 min). **Also the window an external PR reviewer gets:** a freshly opened PR has `PENDING` checks, so the gate can't open before the first post-CI poll — shortening this shortens that window. Don't substitute the build duration for it (a static gate can finish in seconds). |

### What the test gate runs on

The gate is whatever fits the session's cwd: `dev/validate.py` if there is one, else the detected stack's lint, else nothing.
A commit from a repo root with no manifest is **not gated**. That has not changed. A simple command then narrows that gate to
what it changes (ADR 0101):

| Gate | Nothing changed | Something changed |
|---|---|---|
| `ruff check .` | skipped | `ruff check` on the changed `.py`, `.pyi`, `.pyw`, `.ipynb` files under cwd, skipped if there are none. Whole if the commit touches a ruff config, you have a user-level ruff config, a config on the path mentions `include`, `extend-include`, `extension` or `extend`, a tracked lintable name under cwd is a symlink, or a changed path is a directory, submodule or symlink |
| `go vet ./...` | skipped | unchanged, if anything under cwd changed; otherwise skipped |
| `dev/validate.py`, `npm run lint`, `cargo clippy`, `rubocop` | skipped | unchanged, whole |

The stack's lint comes from the cwd itself (never a subdirectory; a `stack:` hint by its first name), and the gate runs a
narrower set of it than `stack-detect` lists: a JavaScript/TypeScript package is gated only by its own `lint` script, and
always as `npm run lint`, whatever package manager the repo declares — npm runs any `package.json` script with no install
state, while `yarn`/`pnpm`/`bun run` can fail before the script starts. With no `lint` script it is not gated, even if `eslint`
is a dependency. A Go module with a golangci config is still gated by `go vet ./...`, not `golangci-lint`. A lint with shell
syntax in it is never run.

*Simple* means an optional single `git add <literal paths>`, `git add -A` or `git add .` joined by `&&`, then `git commit`
with only `-m`, `-a`, `-am`, `-qm`, `--allow-empty`, `--no-verify`, `-q` or `-s` (and their long forms), a heredoc message as
`"$(cat <<'EOF' ...)"` or `-F - <<'EOF'`, or `git push`, `git push <remote>`, `git push <remote> HEAD` or `git push <remote> <current
branch>`, each optionally with `-u`, with `push.default` unset, `simple` or `current`, and no `remote.<remote>.push`. Everything else runs
the whole gate: `git commit -m x && git push`, `cd x && git commit`, `--amend`, a multi-line message in plain quotes. To get the
narrowing, run those as separate calls; a block on one of them says so.

Touching a file makes all of its findings count: this is per file, not per line. A narrowed failure is only a reason to look: the
whole gate then decides, as it always did, and a block shows what the narrowed run found. A block tells the agent to fix the findings
or ask you, and tells you how to skip it: `{"test_gate": {"skip": true}}` in `<cwd>/.agentic-forge/config.json`, written in a separate
call first.

### The PR watcher and the checkout

The scheduled watcher pushes and merges with your `gh` credentials, and the repository is what it is watching, so
the repository does not get a say in what it does (ADR 0103).

- **Settings.** A repo file's `pr_watcher` is removed before the merge. A value that differs from the one in effect
  gets a warning naming the key and not the value, shown once per session. Only `enabled`, `auto_merge` or `auto_watch` set to `false`
  is kept, each overriding your setting with a warning. That is what the clock's own checkout says now: it covers everything that clock
  watches, and does not bind a repo merged by slug or a commit not yet pulled. It is kept also from a
  file that will not parse if it says so clearly. A malformed repo file does not reset your settings.
- **Your tree is not involved.** Each pass fetches the PR's head into no local branch, works in a detached worktree of
  its own under `~/.agentic-forge/state/<repo-slug>/pr-watch-passes/`, even under `state.in_repo`, and removes it
  afterwards, however it ended. A pass never moves HEAD and never reads or changes a file in your checkout, so the clock
  can run in the checkout you work in, with that branch checked out or from a linked worktree. Settings are read once,
  before any PR's tree exists, and the watcher does not open the config file in the PR's tree.
- **Where a queue drains.** The state root is keyed by the checkout's path, with linked worktrees sharing their main
  checkout's. So a created PR is drained by a clock in the checkout that created it, or a linked worktree of it. A
  clock in a different clone has its own empty queue, and says so when it can see one waiting elsewhere.
- **Forks are not fetched.** The watcher does nothing for a fork, so GitHub is asked first and the fork's tree never
  reaches the disk. If GitHub's answer does not say, nothing starts and the pass fails.
- **The fixer runs with the tree as its limit.** Its Claude session has `--setting-sources "" --strict-mcp-config --tools
  Read,Write,Edit,Grep,Glob --permission-mode acceptEdits`. No settings load from the PR's tree or from your home, so
  your own hooks and plugins do not run in it either; Bash and the web do not exist; and a read or write outside the tree
  is denied, including the CLI's own memory under `~/.claude` and the temp output of your other sessions, which it would otherwise exempt.
  A `CLAUDE_CONFIG_DIR` holding a character special to permission rules, such as `[`, gets no session. **It authenticates through the CLI's login or the clock's environment**: an `env` in a `settings.json` is not
  read, and a session that never runs fails the job. The tree's recent commit subjects still reach the model, through the
  CLI's own `gitStatus` block, so this limits what it can do and not what it can be told (ADR 0103).
- **Only threads from people who can already write, or from reviewer apps you list, reach it.** A person needs an association of `OWNER`,
  `MEMBER` or `COLLABORATOR`, and then write, maintain or admin on the repo by GitHub's permission endpoint, asked once a pass and failing
  closed. A reviewer app has to be in `pr_watcher.trusted_reviewers`. Any other thread gets no reply, and holds the merge gate until a person
  resolves it. A dry run says how many are held, and `--health` shows a PR that ran out of ticks that way.
- **What it may change.** A session that changes anything under `.github/`, `.claude/`, `.husky/` or `.agentic-forge/`, or a `.mcp.json`, a `.gitattributes` or
  `.gitmodules`, gets no commit. A denied tool call, or a session that never ran, leaves the thread undetermined, posts
  nothing, and fails the job, as does a `git commit` that fails, for a signer or an identity the clock lacks. A tree where one of those names
  is itself a symlink gets no session, a change to what a link below one leads to gets no commit, and neither does a manual `--apply` on a dirty checkout. A fix is pushed before it is replied to, so a
  refused push posts nothing. A PR that is no longer open gets nothing done.
- **Upgrading from 2026.11.2**: put the clock's checkout back on its branch. The old driver left it on the last PR.
- **Merges are pinned.** A merge passes `--match-head-commit` with the commit the merge gate read.
- **One run at a time.** A second run on the same repo says so and exits `0`. It uses `flock` on the main checkout's
  directory, which a watcher inherits, so a driver killed mid-pass does not free it while its child still works. There is
  no lock on a platform without `flock`. After 6 polls in a row that found it held, it is an anomaly in the diagnostics
  log, and `--health` says so, because a stalled watcher otherwise looks like a quiet one.
- **A failed or refused pass fails its job**, in the sweep as in the drain, so `--health` shows it.
- **Which PRs.** The queue is read from the state root only. An entry naming a repo that is neither this checkout's
  `origin` remote nor in your `pr_watcher.repos` is dropped, with the reason recorded in the diagnostics log and shown by
  `--health` for a week. A renamed repo reads like this: update the `origin` remote. A PR in
  `repos` that is not this checkout's `origin` can be merged, by slug, but gets no fix and no push, because the fixer can
  only push to `origin`: if it has an open thread or a conflict, the refusal is recorded and the job fails. Run a clock
  in a clone of that repo instead. An `origin` that is not a plain `github.com` URL, such as an SSH host alias, names no
  repo here, so that checkout's queue is dropped and its PRs get no fix pass.

### Reviewer skip and failure reasons, and invalid values

An external review that does not produce a verdict is either a **skip** or a **failure**, and neither
is an approval: there is no verdict and no `review.md`. `plugin/bin/external_review.py` prints the
reason and a short redacted detail, and the skills' `review()` returns `None`.

- A **skip** means there was no reviewer to ask: it is absent, disabled, or not the configured one.
  The review round goes on without the lens, and that is expected. Exit `0`.
- A **failure** means the review was asked for and produced no usable verdict: the reviewer was there
  and enabled and the attempt produced no review, or the CLI refused its arguments. The lens dropped
  out of the round, so the workflow records it in the round (`external lens: failed (<reason>)`) and
  tells you, rather than treating it as a skip. Exit `3`.

| Reason | Kind | Meaning | CLI exit |
|---|---|---|---|
| `missing-cli` | skip | The command is not on PATH. | `0` |
| `command-not-configured` | skip | `review()` was passed a `command` other than the configured one. It was not run. | Not reachable: the CLI does not go through this check. |
| `disabled` | skip | `review()` was called with `external_reviewer.enabled` false, at either config level. Nothing ran. | Not reachable: the CLI prints its own message and exits `0`, unless `--force` is passed. |
| `timeout` | failure | No result before the review timeout. | `3` |
| `process-failure` | failure | The CLI exited non-zero or could not be started. | `3` |
| `invalid-output` | failure | It exited 0, but its stdout was not UTF-8, held no review-shaped JSON, or could not prove an approve (see below). | `3` |
| `isolation-unsupported` | failure | `isolated` is on and the capability check did not find both flags. | `3` |
| `refused-input` | failure | The CLI refused its arguments before any call: a `--target` / `--out` refused below, a missing or unreadable `--target`, no `--repo` outside a git work tree, or an `--out` that could not be written (any verdict printed above it is then not recorded). | `3` |

Exit `1` is a `changes` verdict and nothing else. Exit `0` with a `verdict:` line is an approve, and
without one a skip. Exit `2` is a usage error from the argument parser.

**Pass `--repo <the repo whose content this is>`.** The repo's own `.agentic-forge/config.json`, and an
`external_reviewer.enabled: false` in it, is read from `--repo`; the skills always pass it. Without
`--repo` the cwd is taken as the repo. Outside a git work tree that is refused (`refused-input`, exit `3`)
just before anything would be sent, because the diff could belong to a repo that opted out and whose
config would not be read. Inside a git work tree the cwd still works as before.

The review prompt, target included, goes to codex on **stdin** (`codex exec ... -`), not as an argument,
so a large diff is not cut off by the operating system's limit on one argument (128 KiB on Linux), and a
NUL byte in the target does not stop the call. Only the model's context bounds its size. The prompt is
encoded as UTF-8 with `surrogateescape`, so text a caller read with that handler goes out as its original
bytes; any other lone surrogate fails the call (`process-failure`) instead of being replaced. codex runs
with `--skip-git-repo-check` in the `--repo` directory, so a `--repo` that is not a git repo works too:
codex otherwise refuses to start outside a trusted git repo. The read-only sandbox is unchanged.

**What codex loads from that directory**, measured on codex-cli 0.167.0 with the flags the plugin passes,
plain and isolated, using made-up files: from a directory that is **not** a git repo, neither its
`AGENTS.md` nor its `.codex/config.toml` (an MCP server entry that would have left a marker) reached
codex. After `git init` in the same directory, `AGENTS.md` did, isolated too, and the untrusted project
config did not. A control passing the same MCP server with `-c` did start it, so the probe works. So
the reviewed repo's `AGENTS.md` reaches the reviewer, as noted below, and its findings stay advisory.

codex echoes the prompt to its stderr. Before a failed run's output becomes the detail, every line that
appears verbatim as a line of the prompt is removed. This is **best-effort**: it catches the lines the
CLI echoes verbatim, and a line it rewraps or reformats would still show.

A review has a verdict only if the reply holds a JSON object with `verdict` and a `findings` list. If any
such object in the reply says `changes`, the verdict is `changes`, even if the reviewer was only quoting
it, and even beside an `approve`. Its findings are those of every `changes` object, without duplicates.
An `approve` is refused, as `invalid-output`, if the reply also says `"verdict": "changes"` in a form that
did not decode (a trailing comma, `findings` null or missing), or if more than 1000 openings did not
decode, so that the rest of the reply was not read. A `changes` decoded before that limit still decides.
Finding fields lose terminal escapes and control characters and have secrets redacted. Only the first 4000
characters of a field are read: a longer one is cut at a word and ends in `[truncated]`.

`plugin/bin/external_review.py` refuses a `--target` or `--out` that is a symlink, or that goes through a
symlinked directory inside the repo, with a message and exit `3` (`refused-input`), before anything runs. Pass the real path.
A link above the repo root is fine, and so is a path outside the repo. A `--target` that is not a regular
file or not UTF-8 text is refused the same way.

`model` and `effort` must match `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`, so a value cannot become a flag,
and there is deliberately no free-form args key. An invalid string is treated as unset, and an invalid
`command` falls back to `codex`; each gives a warning that names the key and does not echo the value.
The rest of the file still applies, with or without `jsonschema`, because these shapes are checked in
code rather than by a schema pattern.

The only reviewer key a repo file can use is `enabled`. See ADR 0100.

**Set `isolated: true` if you run the reviewer on repos that take outside contributions.** Separately from
this plugin's config, the codex CLI reads project-level configuration of its own. Without isolation, in a
project you have marked trusted in your codex config, that can cause a program the repo chose to run on your
machine during the review, including in a linked worktree of a trusted repo. In an untrusted project it did
not, and with `isolated` it did not in any case. This was measured on codex-cli 0.164.0 and may differ on
other versions. Isolation does not stop everything a repo can say: its `AGENTS.md` reached the reviewer in
every mode, so findings stay advisory.

The schema still checks types and every other key. So a `model` that is not a string or null, or any
other schema error in a file, drops **that whole file** when `jsonschema` is installed. A dropped repo
file does not touch your reviewer settings. A dropped user-level file loses all of them until it is
fixed, including `isolated: true`, except an `enabled: false` it clearly states.

The symlink refusal for `--target` and `--out` treats `--repo`, by default the current directory, as the
repo root: run the CLI from the repo's top level.

A repo's own `enabled: false` is kept when its file is dropped, by a schema error, a JSON typo, a
non-mapping section or its size, as long as the file still clearly says so: the raw text is searched and
what decodes is read. Nothing else in the file is kept. If a file cannot be decoded at all, such as one in
another encoding, or cannot be read, or holds the statement past its first 1 MB, the opt-out **cannot be
known**, so the reviewer stays on and only the warning tells you. For a secret-bearing repo, check that
warning, or also set `enabled: false` at user level.

If a repo's `enabled: false` overrides a user-level `true`, resolving the settings warns, because a branch
can add it to its own config, and the skip detail and the CLI's message say the repo did it. The CLI still
exits `0`.

A dropped file gets one warning, printed to stderr and shown once per session. It says what still applies,
and it gives the JSON path
and the name of the failed schema rule, such as `$.review.passes fails the schema's minimum rule`, and
never the value, because the file may be repo-controlled and the line reaches the session. For the same
reason an unknown top-level key is reported as `$ fails the schema's additionalProperties rule`, without
its name, and a free-form key under `models` as `*`. A file that cannot be read at all, including one
that is not UTF-8 or not parseable JSON, is dropped the same way and never stops a session. So is a file
over 1 MB, without being read, and one the validator itself fails on.

### State and symlinks

Plugin state is written without following a symlink, wherever it lives (ADR 0102). A full write is a temp
file in the same directory and an atomic replace; an append takes regular files only. A write is refused if
the path crosses a symlink, or if the name or a parent is the wrong type, such as a directory at a log's name
or a file at the state directory's. What is checked depends on where state is:

- **In a repo:** `<repo>/.agentic-forge` and everything below it. A checkout controls these.
- **At user level:** everything below the state directory, except `archive/`. A checkout cannot put a link
  at or above that directory, so these are yours and are fine: `~/.agentic-forge`, `AGENTIC_FORGE_STATE_HOME`,
  one repo's `~/.agentic-forge/state/<repo-slug>` and its `archive/` may each be a link.

A refused write is quiet: that record is simply not kept, and an ordinary once-per-session notice shows again.
A hook does not fail over it. A hook-crash notice that cannot be saved shows again as well, because a hook must
not fail silently. The exception is state in the repo, where a checkout could make that happen on every tool
call: there it is not shown, and the crash itself is still recorded if the log can be written. Three cases are
not quiet. The scheduled PR-watch drain fails its job, because an unsaved tick means the same PRs are watched
again. `plugin/bin/run_scheduled.py` exits non-zero and says so if it cannot save its job state, because every
job would otherwise run again on the next poll, whatever its cadence. And a rotation whose archive is refused leaves the log untrimmed, so no record is lost, and records an
anomaly in the diagnostics log at each session start, since the log is growing past its bound. A disk that
cannot take the archive still trims, and the rotation's record says the archive failed.

A full write needs the directory to be writable, even if the file itself is, because of the temp file.

Readers treat a state file behind a link as absent, in the state directory and at the legacy in-repo location,
so its target cannot reach a digest or a diagnostics bundle.

If a repo's committed config set `state.in_repo: true`, its generated state now goes to the user-level root.
Files already in the repo stay readable until a new one is written beside them. The session-start notice gives
the full command, which on its own is a dry run; add `--apply` to merge the files and remove them from the
repo. A legacy `archive/` of rotated logs is not moved: the migration names it and it stays. A file that cannot be
parsed stops the migration with exit `1`, naming the file: it and the ones after it stay, and any reported as
merged by then have gone from the repo. `plugin/bin/state_migrate.py` deletes a legacy `notices.json`, which holds
only per-session markers. It also deletes, without importing and naming each, a legacy `pr-watch-queue.json` and
`schedule-state.json`, which are not read either: a repo can commit a file at those names, and they decide what the
scheduler does (ADR 0103). So a PR queued before the upgrade waits for the next `gh pr create` or for `repos`, and
every job is due once. It
does not follow a link. One at a legacy name is named and kept, and the exit code stays `0`. One at a target is
named, the legacy file stays, and the exit code is `1`, because that target was left unmerged. Any other file in
that directory is left alone and does not raise the notice.

### Vault notes and symlinks

**The vault directory must resolve inside the repo** (ADR 0102). The repo here is the nearest directory, going up
from the working directory, that holds a `.git` entry, so this works from a package inside a checkout; with none,
it is the working directory itself. A link at `docs/knowledge` or `docs` that stays inside, such as
`docs -> website/docs` or a package's `docs -> ../../docs`, works. One that leads outside, however many links it
takes, is not used unless you set `knowledge.allow_external_vault: true` in `~/.agentic-forge/config.json`. It does
not matter who made the link. A linked worktree is its own repo here, so a worktree whose `docs` links to the main
checkout needs the setting. Without the setting:

- `vault.add_note` and `vault.scaffold` raise an error naming the path and this setting, and create nothing.
- Reading acts as an empty vault, with no crash: nothing from it reaches the session context. The session-start
  hook prints one line once per session saying the vault is not read and naming the setting, with no path or text
  from the repo. `vault.validate_vault` reports it as its one problem, so a skill can tell you.

If you keep a vault outside the repo and reach it by a link, you need the setting after upgrading. It then applies
to every repo you open, including one whose link you did not make.

Inside the vault, `vault.add_note` raises an error naming the path if a link or anything but a regular file sits at
the note or at a map-of-content it would link from, or if one it would have to change is read-only, before writing
anything: the note was **not** saved, and the skill's user should be told. That holds with the setting too, and on
a vault that does not exist yet. A map-of-content already holding the link is not changed, and an existing
`README.md` is not written at all, so neither stops a capture. A linked file or folder in the vault is skipped when
reading, never followed, wherever it points, and so is a note that is not UTF-8. Notes are read from every folder
below the vault, within fixed caps on count, depth and size
(see [the knowledge base](architecture/knowledge.md#how-the-vault-is-read)). Frontmatter that does not parse costs
that note its frontmatter, and a `title`, `type` or tag that is not a string is ignored. A note's name and frontmatter title reach the session context by
design (ADR 0018), and a repo chooses both.

## Env-var overrides

These win over both files (an empty value is ignored, so `export VAR=` can't clobber a file):

| Env var | Overrides |
|---|---|
| `AGENTIC_FORGE_DIAGNOSTICS` | `diagnostics.enabled` |
| `AGENTIC_FORGE_SUBAGENT_SOFT` | `subagent_budget.soft` |
| `AGENTIC_FORGE_SUBAGENT_HARD` | `subagent_budget.hard` |
| `AGENTIC_FORGE_SKIP_TEST_GATE` | `test_gate.skip` (a boolean like the others: `0`/`false` keep the gate — ADR 0094) |
| `AGENTIC_FORGE_LOGS` | `logs.enabled` |
| `AGENTIC_FORGE_ROUTING_NOTE` | `routing_note.enabled` |
| `AGENTIC_FORGE_PRE_ROUTER` | `pre_router.enabled` |
| `AGENTIC_FORGE_STATE_HOME` | the state root itself (not a key): where runtime state lives when the default is not wanted (ADR 0072) |

## Enabling the logger (example)

To turn the diagnostics log on for **every** project, put this in `~/.agentic-forge/config.json`:

```json
{ "diagnostics": { "enabled": true } }
```

…or set it for one repo only in `<repo>/.agentic-forge/config.json`, or once via
`AGENTIC_FORGE_DIAGNOSTICS=1`. Then read the log with
`python dev/diagnostics_digest.py --repo <path>`.

## Which Python do you need?

Two different answers, and conflating them cost a real user a debugging session:

- **Using the plugin (hooks, shipped skill scripts):** whatever `python3` is on PATH, **3.9 or
  newer**, with **no third-party packages**. The hook-reachable modules are stdlib-only at import
  time and every shipped file carries `from __future__ import annotations` (Tier-0 enforces this),
  so macOS CommandLineTools' pinned 3.9.6 works as-is — this is the field-verified baseline.
- **What a skill runs (`bin/af.py`, ADR 0104):** the same `python3`, with `-E`, and nothing installed for most of it.
  Reading a handoff artifact (`handoff-load`, `plan-batches`) also needs PyYAML and jsonschema: without them it exits 3,
  names the package and says nothing was checked, and a spine phase then escalates (never `review_decision: proceed`) and commits nothing. To
  enable it, `python3 -m pip install pyyaml jsonschema`. `-E` keeps user site-packages, so a `--user` install counts.
- **Developing the plugin** (running `dev/` CLIs, `pytest`, the eval gates): Python **≥ 3.11** plus
  the dev deps (`pip install -e .`) — that is what `pyproject.toml`'s `requires-python` describes.

Config is validated with `jsonschema` when it is installed. A guardrail hook may run under a bare
`python3` without it; in that case a committed config is loaded **unvalidated** (trusted) rather than
dropped, and every value is coerced defensively so resolution never crashes (ADR 0050). Install the
plugin's deps (`pip install -e .`) for schema validation and the knowledge-vault session injection.
