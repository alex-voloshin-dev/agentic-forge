# Layer 4 — Guardrails (hooks)

Status: **Built** ([ADR 0019](decisions/0019-l4-guardrails.md)) — deterministic guardrail
hooks on tool use (the role-scope hook added by [ADR 0106](decisions/0106-the-read-only-roles-are-held-by-a-hook.md)), on top of L3's session-start hook. **Scheduling & observability shipped
separately** ([ADR 0024](decisions/0024-stage7-scheduling-observability.md),
[scheduling-observability.md](scheduling-observability.md)); this doc covers only the hooks.

The guardrails turn the project's discipline into **enforcement**: a hook deterministically
blocks (or warns) where a CLAUDE.md rule would only advise. They live under `plugin/hooks/`
(`hooks.json` + `scripts/`) as thin glue over `lib/agentic_forge/guardrails.py` (deterministic,
100% tested). Each hook **fails open** on its own error — a guardrail bug must never break a
session — except where blocking is the whole point (security, test-gate). A crash is never silent:
it is recorded to `diagnostics.jsonl` even with `diagnostics.enabled: false` (the one exception to
the opt-in, like outward actions) and announced once per session as a `systemMessage` — "hook
crashed: … — failing open" — because a dead guardrail otherwise looks exactly like a healthy one
(ADR 0094).

## The hooks

- **security** (`PreToolUse` / Bash, `security.py`) — blocks clearly-dangerous commands via a
  conservative deny-list: recursive/forced `rm` or permissive `chmod` of `/`/`~`/a system dir,
  fork bombs, a network download piped into a shell/interpreter, `mkfs`/`dd` to a device, raw-disk
  writes, a `find <root/system-dir> … -delete` (whole-tree delete), and force-push (`--force` or a
  `+refspec`) to a protected branch. Exit 2 blocks;
  everything else is allowed (false positives cause friction, so it blocks only unambiguous hazards).
  Every rule fires on the **command word** of a **quote-aware segment** (ADR 0051 for the
  network-download rule, ADR 0054 for the rest): segments split on `;`/`|`/`&`/newline *outside
  quotes*, tokens come from `shlex`, and the rule's command must be the segment's command word
  (after `sudo`/env-assignment/wrapper prefixes). So `ls /usr && rm -rf build` is not misread as
  `rm -rf /usr`, and a command that merely *quotes* a dangerous string — `git commit -m "block
  rm -rf /"`, `grep "rm -rf /" docs/`, a `python3 -c` script holding the pattern — never blocks,
  while executable payloads (`bash -c "rm -rf /"`, `$(…)`/backtick substitutions) are re-classified
  recursively and still do. The network-download check additionally requires a **bare** interpreter
  (one reading *stdin as its program*) fed from a **non-loopback** host — so `curl localhost … |
  python3 -c` (local observability) and `… | python3 -m json.tool` (data parsing) pass while
  `curl https://…/install.sh | sh` blocks. A segment `shlex` cannot tokenize (unbalanced quotes)
  degrades to the pre-0054 text checks — block-leaning, never silently passing.
  The hook reads the Bash command line and nothing a script does inside it. That is why `plugin/bin/af.py` returns a
  commit, a push or a merge for the session to run rather than running it (ADR 0104); a command that holds only `af.py`
  and its flags is allowed, and a quoted heredoc feeding it is data (ADR 0079). The force-push rule accepts an optional
  `refs/heads/` on the destination, since that is the form `pr-state`'s `push` takes.
- **test-gate** (`PreToolUse` / Bash, `commit_gate.py`) — on `git commit`/`git push`, runs the
  **fast** gate (`dev/validate.py` if present, else the detected stack's lint via `stacks.py`) from
  the session's `cwd` and blocks on failure, so broken code isn't committed. The stack is the
  cwd's own, read as before the monorepo scan and multi-name hints (`stacks.gate_profile`: no
  scan, a hint's first name, the hint file wherever it links), and the gate keeps only lint shapes
  that cannot make it block where it used to pass (`guardrails._gate_argv`): a JS/TS package's own
  `lint` script, always as `npm run lint` — npm needs no install state, while `yarn`/`pnpm`/`bun
  run` can fail before the script starts (Yarn Berry not installed in a fresh worktree, a corepack
  download, `ERR_PNPM_BAD_PM_VERSION`) with an exit 1 the fail-open signatures do not know; no
  script, no gate, so a declared `eslint` stays a fallback for a person — `go vet ./...` even where
  the profile names `golangci-lint`, no `tflint` (a Terraform profile names it when `.tflint.hcl`
  exists; Terraform was never gated, and tflint may need `tflint --init` first), and nothing with
  shell syntax. Skippable via
  `test_gate.skip` or `AGENTIC_FORGE_SKIP_TEST_GATE`;
  fails open on an infrastructure error (missing tool, timeout) **and when the gate can't run** —
  a non-zero exit whose output shows a missing lint script / uninstalled linter
  (`guardrails.gate_unrunnable`, specific signatures only) **or** a shell not-found exit code
  (127/126) is environment breakage, not a code-quality signal, so it is downgraded to an `anomaly`
  and allowed rather than blocking a commit. The signatures are deliberately narrow — a bare
  `not found` / `no such file` would match genuine failures and wrongly let broken code commit
  (ADR 0058, tightened by ADR 0059).
  **A simple command narrows that gate, and can only narrow it** (`gate_scope.py`, ADR 0101). The
  gate is still what `choose_gate(cwd)` picks: a commit from a root with no manifest stays ungated.
  A small strict matcher accepts an optional single `git add <literal paths>` / `-A` / `.` joined by
  `&&`, then `git commit` with flags that cannot widen what it takes (a `-m "$(cat <<'EOF' …)"`
  message or `-F -` included), or `git push`, `git push <r>`, `git push <r> HEAD` or `git push <r>
  <current branch>`, each optionally `-u`. For those, git says what changes: staged paths, plus
  tracked changes for `-a`, plus what a `git add` covers including untracked files; for a push that
  can only send this branch to its own name, the files in commits that its tracking ref lacks, or
  `--not --remotes=<r>` where there is no such ref, merge diffs included. An empty set skips any
  gate, so an empty commit passes. `ruff check .` becomes `ruff check ./a.py …` over the lintable
  changed files under `cwd`, and is skipped when there are none, so old findings in other files do
  not block. It stays whole when the commit touches a ruff config, a user-level ruff config exists,
  a config on the path mentions a key that chooses its own inputs, a tracked lintable name is a
  symlink, or a changed path is a directory, gitlink or symlink. `go vet ./...` is skipped only when
  nothing under `cwd` changed. Every other gate runs whole. Any non-zero narrowed exit runs the
  whole gate and applies the classification above to that result, so a block happens only where the
  gate would have blocked anyway; an explicit path reaches files `ruff check .` does not walk. **Any
  other shape, any character the matcher does not understand, `GIT_CONFIG_COUNT`,
  `GIT_CONFIG_PARAMETERS`, a `GIT_DIR`-style variable, or any git failure behaves exactly as
  before.** A block tells the model what ran on what, with the
  output redacted, and to fix the findings or ask the user. The operator's `systemMessage` carries
  the way out: `test_gate.skip: true` in `<cwd>/.agentic-forge/config.json`, in a separate call
  first. A block on a refused shape adds that running `git commit` or `git push` as its own call
  gates only what changed.
  **The gate is `PreToolUse`, so it blocks the *whole* Bash command before any of it runs** — a
  prerequisite the gate itself needs cannot be established in the same command. `ln -sfn …/node_modules
  ./node_modules && git commit -m …` fails permanently: the gate runs `npm run lint` first, the
  linker has not run yet, and eslint is missing. Establish prerequisites in a **separate, earlier**
  command (one with no `git commit` substring anywhere in it), verify the tool resolves, then
  commit. The narrowing above removes this edge only where it applies: a simple commit that changes
  nothing a ruff or go gate reads needs no lint toolchain. A compound command like the one above, and
  a whole-package tool such as `npm run lint`, keep it (field report AF-04).
- **security: no remote environment dumps** — a bare `printenv` / `env` / `set` reaching a remote
  host through `kubectl|oc exec`, `ssh`, `docker|podman exec`, `fly ssh` or `heroku run` is blocked.
  A prefix-filtered dump eventually matches a secret whose name *starts with* a non-secret prefix
  (field case: `SCORING_VNEXT` matched `SCORING_VNEXT_CRUX_API_KEY` and printed it into the
  transcript). Local dumps, exact-name lookups (`printenv PGHOST`), `env`/`set` used as wrappers,
  and a dump piped through a redaction filter (`| grep -ivE 'KEY|SECRET|…'`) all pass (ADR 0075).
- **merge preflight** (`PreToolUse` / Bash, `merge_preflight.py`) — on `gh pr merge`, two things:
  - **The merge gate: blocks** a merge the PR watcher would hold (field report f993da46). GitHub
    lets a PR merge when its `mergeStateStatus` is `UNSTABLE` (a check that is not *required* is
    red) and ignores unresolved review threads unless branch protection requires their resolution;
    the watcher refuses both, but a session running `gh pr merge` itself used to get only the local
    warnings below. In the field, a PR with a red non-required Terraform test (after a semantic
    conflict with another PR) and an open review thread was merged that way.
    - **Which PR.** `guardrails.pr_merge_target` reads the command as a shell would: quotes,
      `\`-newline continuations, comments, and redirections (`2>&1`, `2>/dev/null`, `> out.txt`,
      `&>log`) are the shell's, not PR arguments. It takes a number, URL or branch (none: the
      current branch's PR), `-R`/`--repo` (one flag; the **last** one wins, as in `gh`), a
      `GH_REPO=` or `GH_HOST=` prefix, and a literal `cd`/`pushd` before the merge that surely
      takes effect (unconditional, or chained to the merge by `&&` alone; not in a pipeline or
      the background). Then two read-only `gh` calls, `gh` run by its **absolute** path only (a
      relative or empty PATH entry could find a `gh` committed to the repo): `gh pr view [<pr>]
      [-R <repo>] --json number,url,mergeStateStatus`, which resolves the PR exactly as `gh pr
      merge` would, and the watcher's own GraphQL query (`pr_watch.PR_QUERY`) for that number,
      parsed by the watcher's `parse_pr`. The GraphQL call always passes `--hostname <host of the
      resolved PR URL>`, github.com included: a `GH_HOST` for the merge would otherwise send it to
      another host, and so another PR, than the one `gh pr view` found.
    - **Which hosts it contacts.** A `PreToolUse` hook runs *before* the permission prompt, so a
      host the command names — perhaps through injected text — would be called, with any exported
      `GH_ENTERPRISE_TOKEN`, even if the operator then denied the merge. So before any `gh` call,
      the host the command names (a URL's, `-R HOST/OWNER/REPO`'s, or `GH_HOST`'s) must be
      `github.com` or the host of the checkout's own `origin` remote (read locally, `git config
      --get remote.origin.url`); the host of the PR `gh pr view` resolved is held to the same rule
      before the GraphQL read. Anything else fails open with a notice that does not echo the host.
    - **Only what reads may run before the merge in the same command.** The gate reads the PR
      *before* the command runs, so anything earlier in it that could change the PR, its checks
      or which PR is meant would make it judge a state the merge never sees — `gh pr checks
      --watch && gh pr merge` (it would block a merge that waits for green), `gh pr ready && gh pr
      merge`, resolving threads through `gh api graphql` then merging, `gh pr checkout 12 && gh pr
      merge`, `git checkout x && gh pr merge`, `sleep 300 && gh pr merge`, an `export GH_REPO=…`.
      The allowlist is short: `cd`/`pushd` (followed), `gh pr view|status|diff`, `gh pr checks`
      without `--watch`, `git status|log|diff|fetch|rev-parse`, `echo`, `true`, and a plain
      variable assignment that is not `GH_*`/`GITHUB_*`/`GIT_*`. An allowlisted command must be
      the plain command word (no wrapper, no assignment before it), redirect output to nothing but
      `/dev/null` or a descriptor (`echo x > .git/HEAD` writes), and, for git, carry no global
      flag but `--no-pager`, `-P`, `--no-optional-locks`, `--literal-pathspecs` or
      `--no-replace-objects` (`-c`, `-C`, `--git-dir`, `--work-tree` and `--exec-path` change
      the repo or the program) and no `--output*`, `--ext-diff` or `--upload-pack*`. Anything
      else, before the merge, makes the command unattributable. What comes *after* the merge does
      not matter.
    - **The merge itself must be plain**: `gh` as the command word, with only `GH_REPO`, `GH_HOST`,
      a token or an output-only variable (`NO_COLOR`, `GH_PAGER`, ...) assigned for it. A wrapper
      before it (`env -C /x`, `sudo -D /x`, `command`, `nice`, `timeout`, `xargs`) may run it
      elsewhere, a reserved word (`if … then`, `{ … }`, `!`, `while`/`until … do`, `time`) may not
      run it at all, and `GIT_DIR`/`GIT_WORK_TREE` change which repo `gh` resolves: each fails
      open, and `is_pr_merge` sees through them (and through a `\`-newline between `pr` and
      `merge`) so that it is a notice, not silence.
    - **The decision** is `pr_watch.session_merge_gate`, sharing its clauses and their wording with
      the watcher's `merge_readiness`. It exits 2 with `merge gate: #<n>: merge held: <reasons>`
      (plus GitHub's `mergeStateStatus`) when the PR is a **draft**, its check rollup is
      **pending, failing or erroring** (anything but `SUCCESS`), it has an **unresolved review
      thread** not by `pr_watcher.bot`, or its thread list is past the 100 the query reads. A PR
      with **no checks at all** merges, with a notice: a repo without CI must be able to merge
      (the watcher still holds it — "no builds" is not "green builds", ADR 0063). `--auto` is held
      like a merge, since auto-merge waits only for *required* checks — **so a session cannot
      queue an auto-merge while checks are pending**; it waits for them, then merges.
      `--disable-auto` and `--help` merge nothing and call nothing. The session gate is a
      **subset** of the watcher's, so it never refuses a merge the watcher's gate opened: a fork,
      `mergeable` and a review requesting changes stay the watcher's. Nothing the PR's author wrote
      reaches the message — no title, body, thread text or check name; only the PR number and enum
      values GitHub sends, and a non-enum value reads `UNKNOWN` or is left out. A block is recorded
      in the diagnostics log (rule `merge-gate`).
  - **An accident guard, not a security boundary.** It stops a session merging by mistake what the
    watcher would hold; it does not stop one that sets out to merge. Whatever it cannot attribute
    **fails open with a one-line notice** (on stderr and, since a hook's stderr on exit 0 reaches
    nobody, as a `systemMessage`) — never a silent pass, never a block on a guess: `gh` not on
    PATH or found through a relative PATH entry, a host that is neither github.com nor the
    checkout's origin, not logged in, an API or network error (any
    non-zero exit), no answer within the budget, output that is not JSON or does not describe the
    PR it asked about (a tolerant parse of an empty answer would otherwise read as "no checks"), a
    PR that is not open (`gh` refuses it itself, but a lookup that found the wrong PR must not pass
    unremarked), or a command it cannot attribute to one PR as it will be when it merges: two
    merges, a flag `gh pr merge` does not have, a non-bool value for a bool flag, another `GH_*`
    variable for the merge, a shell expansion in it, a command substitution, subshell or group
    before or around it, a wrapper or reserved word around it, a `cd` that may not take effect,
    anything before it off the allowlist.
    The notice says which. Echoed reasons name the `gh` call and its exit code, or a plain word
    from the command, never `gh`'s own output. **What it does not see at all**, and so does not
    gate: a merge through `gh api -X PUT repos/<o>/<r>/pulls/<n>/merge`, through `sh -c '…'` or
    a script, through a `gh` alias, inside a `case` arm or a function body, through `env -S`, or by
    any route that is not `gh pr merge` in command position. The `origin` whose host may be
    contacted is the session's checkout, never a directory the command `cd`s into.
  - **Cost**: nothing for any other command — the check is the existing `is_pr_merge` parse, and
    `pr_watch` is imported only on a merge. On a merge, two `gh` calls (two API round trips)
    within one 12 s deadline; the git reads keep their own 12 s, and the hook's timeout in
    `hooks.json` is 30 s (it was 15 s), so a stalled `gh` is a notice rather than a killed hook.
  - **The local warnings** (git run by its absolute path only, like `gh`; without one they are
    skipped with a notice) read `origin/HEAD`, the worktree list and the base branch's
    ahead-count, and **warn** when another worktree holds the base branch or local `base` is
    ahead of upstream — the two conditions that break the *local* half of the merge (`'master' is
    already used by worktree`, `Not possible to fast-forward`). These **never block**: the merge
    itself happens on the server and is durable, and the base branch is only approximated from
    `origin/HEAD` (ADR 0076). The main checkout holding the base is normal and stays silent.
- **pre-router** (`UserPromptSubmit`, `pre_router.py`) — names the skill a prompt clearly
  matches, in the prompt's own `additionalContext`, so the model reads the suggestion at the
  moment it decides whether to invoke a skill or do the work by hand (ADR 0089). Deterministic:
  a lexical classifier over each skill's description and its `evals.json` trigger prompts, no
  model call, a few milliseconds. Abstains unless one skill wins clearly (coverage ≥ 0.40, lead
  ≥ 0.15 over the runner-up, not vetoed by the skill's own anti-triggers); leave-one-out on the
  plugin's own data: recall 0.463 (37/80), precision 0.974, wrong-skill 1, false-suggest 0/68 over the
  16 shipped skills (re-measured in ADR 0105; thresholds recalibrated in ADR 0092). A request to author a
  new skill, agent or component ("create a skill for X", an authoring verb, then "a" / "an" / "new") abstains outright: its owner `skill-factory` is a maintainer skill the
  shipped index does not hold (ADR 0105). It **suggests, never
  invokes** — the line ends "if the request is really something else, ignore this" — because a
  hook that overrides the prompt is the ADR 0073 failure. **Off by default** (`pre_router.enabled`,
  `AGENTIC_FORGE_PRE_ROUTER=1` to opt in): measured at +0.095 over the session note — inside
  single-run noise (z = 1.27), an upper bound because the eval prompts are the classifier's own
  training set — on a stand ADR 0090 then found empty, so the null result is uninterpretable; it
  stays off because the honest baseline left it nothing to fix (ADR 0091). Fails open and records
  the crash.
- **budgets** (`PreToolUse` / Task, `budget.py`) — a per-session subagent counter; **warns** over
  the soft cap and **blocks** over the hard cap (`AGENTIC_FORGE_SUBAGENT_SOFT` / `_HARD`).
- **role scope** (`PreToolUse` / every tool but Read, Grep and Glob, `role_scope.py`) — holds the
  read-only roles (`reviewer`, `security-engineer`, `grader`, `architect`) to their tool scope in
  every permission mode, by allowlist, and runs a lens's git call in a hardened form; silent for
  every other caller. See [Role scope](#role-scope) below (ADR 0106).
- **logging** (`PostToolUse`, `audit_log.py`, gated by `logs.enabled` / `AGENTIC_FORGE_LOGS` — **on by default**, ADR 0078) — appends a secret-redacted JSONL audit line to
  `~/.agentic-forge/state/<repo-slug>/audit.jsonl` (out of the project checkout — ADR 0072). Redaction
  (`guardrails.redact_secrets`) masks known token shapes, secret-named assignments (`*PASSWORD*`, `*TOKEN*`,
  `*SECRET*`, `*KEY*` forms, `*PWD*`, `*CRED*`), the value after secret flags (`--password`, `--token`, `--api-key`,
  …), `sshpass -p` and the MySQL clients' attached `-p<value>`, reading each value as a whole shell word. It is a best
  effort over text, not a shell parser: unusual quoting can still leave part of a value in clear, so credentials
  belong in files or the environment, not on a command line. Pure observability; **never blocks**. Each record also
  carries `error: true` when the tool call clearly failed (`guardrails.tool_errored`, additive —
  absent on success), so the digest can rank tools by *failure*, not just usage (ADR 0058). The log
  dir is the **main** working-tree root (`diagnostics.main_repo_root` resolves a linked worktree's
  `.git` file back through its `gitdir:` pointer), so a worktree-phase trail survives the worktree's
  removal; diagnostics events are normalised the same way. The session-start hook rotates the log
  once per session above a size bound (`observability.rotate_audit`, keep-the-tail). Like every state
  writer it goes through `state_io`, which does not follow a symlink, and a refused write is dropped
  quietly (ADR 0102).
- **PR created** (`PostToolUse` / Bash, `pr_created.py`) — notices a real `gh pr create` (matched at
  a **command position** on a quote-aware segment, so `gh pr view` and a quoted mention in a
  `--body` don't fire) *and* the PR URL `gh` printed on success, then injects a notice as
  `additionalContext` + `systemMessage` (ADR 0063; it was bare stdout, which a PostToolUse hook shows
  to nobody — ADR 0094). The notice says who can do what: `/pr-watch` is a manual command for the
  user (the skill is `disable-model-invocation`), and an agent checks the PR with `gh` itself. This
  is the only mechanism that can fire automatically on PR creation — a skill cannot observe a command it did not run. It **only suggests**: it never spawns
  the watcher, because auto-merge sits downstream of that signal and a guardrail layer must not
  silently start an agent that can merge. Pure observability; **never blocks**.

## Role scope

The architect's Write scope outside `docs/` was widened narrowly by ADR 0110.

A plugin agent's `tools:` list does not restrict what a `Bash(...)` specifier names: `reviewer` and
`security-engineer` declared `Bash(git diff:*)` and got Bash. What kept them read-only was their
prompt and, in `default` mode, the session's permission prompts; in `bypassPermissions` nothing did
(ADR 0106 has the measurement). A lens reads untrusted content by design, the diff under review, so
the boundary has to hold against that content, in every mode.

**How the hook knows who is calling.** The `PreToolUse` payload of a tool call made inside a
subagent carries `agent_type`, e.g. `"agentic-forge:reviewer"`; a call from the main session carries
none. `role_scope.decide` (in `lib/agentic_forge/role_scope.py`, pure and fully tested) matches the
**namespaced** form only. Claude Code names a plugin's agent `<plugin>:<agent>`, and a bare
`reviewer` is a project's or a user's own agent, which this plugin has no business restricting. A
test pins the namespace to the manifest's `name`. A call with no `agent_type`, or any other value, is
allowed with no output, and so is the plugin's own other roles' (the script exits on any
`agent_type` that is not a held role). It loads only `json` and `sys` before that exit, so the hook
costs the main session one Python start and a JSON parse per call: 26 to 30 ms median, about 20 ms
of it the interpreter's start, measured on WSL2 with CPython 3.12 (ADR 0106).

**The allowlists.** Taken from each role's own `tools:` line (a test keeps the two equal):

| Role | Allowed | Bash |
| --- | --- | --- |
| `reviewer`, `security-engineer` | Read, Grep, Glob, Bash | one read-only git command (below) |
| `grader` | Read, Grep, Glob | refused |
| `architect` | Read, Grep, Glob, Write (Markdown design documents under `docs/`, or in a feature folder or ADR directory the repository already keeps, below) | refused |

Any other tool is refused for these roles: Edit, MultiEdit, NotebookEdit, WebFetch, WebSearch,
Agent/Task, Monitor, PowerShell, Skill, every MCP tool, and any tool added later. The matcher is the
regular expression `^(?!(?:Read|Grep|Glob)$).*`, which Claude Code evaluates as a JavaScript regular
expression: every tool name but those three exact ones reaches the hook, so the allowlist is not
bounded by a list of names somebody has to keep current.

An architect's Write is an allowlist that fits its contract, design documents. The resolved path
(relative to the session's `cwd`, symlinks followed) must lie under `docs/` of a working tree of the
session's repository, its checkout or a linked worktree (the same walk as `-C`; a submodule or a
nested repository is not one); it must end in `.md`; no segment below that tree's top may start
with `.`; and its name may not be `CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md`, `GEMINI.md` or
`SKILL.md`, case-insensitively. So the user's shell and git configuration, `.mcp.json`,
`~/.claude.json`, `.claude/agents/`, the agent instruction files and skill definitions are out, as
is any file that is not a document. `docs/` is the role's contract directory: the `architecture`
skill has it write `docs/sdlc/<slug>/*.md` in the feature's doc-delivery worktree, a linked worktree
beside the repository, when the repository keeps no feature folders of its own.

**Outside `docs/`: the repository's own feature folders.** A repository that keeps its features
under, say, `features/in-progress/<slug>/` and its decisions in `features/architecture/adr/` has
the `architecture` skill write there (`af.py artifact-home`, see
[handoff.md](../../plugin/patterns/handoff.md#where-a-features-documents-go)), so the role must be
able to. The widening is the narrowest that serves it: a Write outside `docs/` passes only when
**all** of these hold, on the resolved path, after every check above (same working tree, no hidden
segment, no instruction or skill file, `.md`, the blocklist):

1. **The target's directory already exists**, below the working tree's top (never the top itself),
   every component of its path below the top is letters, digits, `.`, `_` and `-` (not starting
   with `.` or `-`), and it is one the repository keeps for these documents
   (`role_scope._feature_home`, over the predicates `artifact_home` detects with — `dir_names`,
   `marks_feature`, `holds_series` — so the hook allows what the detector proposes, **and any other
   existing folder of the same shape**: it does not re-run the detection for a slug):
   - a **feature folder**: its name has a slug's shape (`[a-z0-9][a-z0-9-]*`) and it holds a feature
     document (`prd.md`, `plan.md`, `design.md`, `tech-design.md`, `research-brief.md` or
     `ux-spec.md`) as a regular file (case-insensitively; a symlink does not count);
   - an **`adr`, `adrs` or `decisions` directory** directly in such a folder;
   - an **ADR series directory**: it holds a numbered decision record (`adr-001-x.md`,
     `ADR-G01-x.md`, or `0001-x.md` in a directory named `adr`, `adrs` or `decisions`).
2. **The file name is the role's contract**: `tech-design.md`, or a decision record (`adr-*.md` /
   `adr_*.md`, or a member of the directory's numbered series). The other feature documents — a
   PRD, a plan, a research brief, a UX spec — are other phases', which the main session writes and
   this hook does not hold; the architect cannot write them outside `docs/`, nor a `README.md` or a
   contributor guide beside them.

Why this shape. The rule is **detection, not configuration**: a repository's config may only switch
things off (ADR 0102/0103), and a path list in a checked-in file is exactly what a pull request could
widen. Requiring the directory to exist means the role cannot bootstrap a new home: it cannot write
into a fresh directory to make it a feature folder, because the fresh directory does not qualify,
and it cannot write a feature document there anyway; the orchestrating skill (the main session,
which this hook does not hold) creates a new `adr/` with the `mkdir` command `artifact-home` prints
when it says `create_dir`. Excluding the top keeps a root-level `PLAN.md` from opening the root, and
the detector proposes no series at the top for the same reason. The checks read **one listing of
the target's directory, and one of its parent** only when the directory is named `adr`, `adrs` or
`decisions`; each is capped at 10,000 entries and never goes through a symlink; any error is a no,
which refuses, and an exception is the hook's fail-closed path. What remains reachable: the design
and decision records in such a directory, overwriting an existing one included. That is the role's
job, and the commit is the skill's, reviewed in the feature PR.

A `..` from one working tree into the hidden space around another (where linked
worktrees and `.git` live) is refused as outside the session's working trees. Under it the first blocklist stays as a second layer, on the path as given and as resolved,
case-insensitively: a `.git` component, `.claude/settings*.json`, `.agentic-forge/config.json`.

**The read-only git rule** is an allowlist checked in this order, and the first failure is the
reason given:

1. **One simple command.** No `;`, `&`, `|`, `<`, `>`, backtick, `$` in any form, backslash, newline,
   NUL, other control character or lone surrogate, anywhere in the string, quoted or not. With no
   backslash, quoting is plain and `shlex`, bash and zsh agree on where a quote ends. Outside quotes
   a word may hold only letters, digits and `_ . / : @ , = + % ~ -`, so no glob, brace, grouping,
   history or zsh extended-glob character (`^`, `#`) reaches the shell, and it may not start with
   `=` (zsh's `=cmd`), quote marks before it included. A quoted pathspec such as `-- 'src/*.py'` is
   git's to match and is fine, as is a quoted `'HEAD^'`. The string is then tokenized with `shlex`
   (POSIX rules, the same quote removal the shell does).
2. **`git` is the first word**, exactly; no path, wrapper or environment assignment before it.
3. **Global options:** only one `-C <path>` and `--no-pager`. A `-C` path must be the top of a working
   tree of the session's own repository: its main checkout, a linked worktree or a submodule,
   recognised by the `.git` entry it holds pointing into the session repository's git directory. A
   directory that merely has a repository's shape is not one, so git is never pointed at a config
   the reviewed change could supply. A second `-C` is refused (git resolves each relative `-C` from
   the one before), and so is a `~` anywhere in the path (a quoted tilde reaches git literally);
   the path is resolved as `chdir` resolves it, with no expansion.
4. **The subcommand** is one of `diff`, `show`, `log`, `status`, `blame`, `ls-files`, `ls-tree`,
   `rev-parse`, `merge-base`, `cat-file`, `grep`, `shortlog`, `describe`.
5. **No option that writes a file or runs a configured program**, anywhere in the command:
   `--output`, `-o`, `--ext-diff`, `--textconv`, `--filters`, `-c`, `--config-env`, `--exec-path`,
   `--upload-pack`, `--paginate`, `--open-files-in-pager` (and `grep`'s `-O`, in a bundle too),
   `--help`, `--no-index` (which takes git outside the repository), `--submodule` (its `diff` form
   starts nested diffs that do not inherit `--no-ext-diff`) and `--show-signature` (gpg). A token is
   refused when it is one of these, starts with one (`--output=f`), or, for a long option, is an
   abbreviation of one, since git accepts a unique prefix. The prefix rule is deliberately coarse: it
   also refuses the harmless `--output-indicator-new`, `-old` and `-context`, which a lens does not
   need. `--text` passes only for `diff`, `show`, `log` and `grep`, whose man pages list it as its own
   option; for any other subcommand git would read it as `--textconv`. Any signature placeholder
   (`%`, an optional `+`, `-` or space modifier, then `G`) is refused, as a second layer under the
   gpg settings below, and so is a `--pretty=`/`--format=` name that is not a built-in format (a
   `pretty.<name>` alias from config could hold one). `cat-file` takes only `-p`, `-t`, `-s` and `-e`;
   its other options run textconv or filters, or read object names from stdin, which a lens cannot
   supply. `-p` after `log` or `show` is a patch and is fine; as a global option it is refused by
   rule 3.

**What runs is what was checked.** An allowed git call is not passed through. The hook answers with
`permissionDecision: "allow"` and an `updatedInput` whose `command` is rebuilt from the checked words,
every word single-quoted, prefix included, so neither bash nor zsh expands anything in it whatever
its options, behind a fixed hardening: `/usr/bin/env -u <variables> GIT_NO_LAZY_FETCH=1 git
-c safe.bareRepository=explicit -c core.fsmonitor=false -c core.hooksPath=/dev/null
-c diff.submodule=log -c log.showSignature=false -c format.pretty=medium
-c core.attributesFile=/dev/null -c gpg.program=/dev/null -c gpg.ssh.program=/dev/null
-c gpg.x509.program=/dev/null --no-pager`, then `--attr-source=<the empty tree>` on git 2.41 and
later, the resolved absolute `-C` path, the subcommand, `--no-ext-diff --no-textconv` for `diff`,
`show` and `log` and `--no-textconv` for `blame` and `grep`, then the arguments. Command-line `-c`
outranks every config file, an included one too, and reaches the git processes git starts.

Turned off for the call: an external diff program, textconv, the pager, hooks, fsmonitor, nested
submodule diffs (a submodule's change shows as a log), signature verification (`log.showSignature`,
or a default format holding `%G`, would run gpg) and every signature program (set to `/dev/null`,
which cannot run), the global attributes file, implicitly found bare
repositories, the git variables cleared below, and on git 2.41 and later every attribute the
checkout's `.gitattributes` sets, so no clean filter, diff driver or textconv is selected; on git
2.44 and later, lazy fetching in a partial clone. The hook asks `git --version` once per call, with
a 3 s timeout, of the `git` on its own `PATH` and only by an absolute path; an unknown version gets
`--attr-source`, so a git that rejects it fails to start instead of running without it. The hook's
`PATH` can differ from the shell's: a newer git in the hook and an older one in the shell fails
closed; the reverse leaves the option out and that call has the old-git residual. Not turned off: on git older than 2.41, a checkout's
`.gitattributes` can still select a clean filter the user's own config defines, which `status`, a
worktree diff, `blame` or `describe --dirty` runs (refusing those would stop reviews on the git
2.39 that Apple, Debian 12 and older Ubuntu releases ship; ADR 0106); attributes in
`$GIT_DIR/info/attributes`; on git older than 2.44, lazy fetching.

`env -u` clears the variables that point git at another repository, index, object store, attribute
source or config, that name a program (diff, pager, editor, ssh, askpass, proxy, exec path) or that
name a file git writes (the trace targets); the Bash tool's shell can set variables the hook's own
environment never sees, which is why they are cleared rather than checked. `updatedInput` replaces the whole tool
input, so the hook copies the call's other fields and drops only `dangerouslyDisableSandbox`;
Claude Code still applies the user's deny and ask rules to the rewritten command. ADR 0106 records
the contract and its source. The checks above stay as a second layer, and a rewritten command sent
back is checked as the plain one and rewritten to the same text.

**The refusal** is the `PreToolUse` `deny` decision on stdout (`hookSpecificOutput.permissionDecision`
with exit 0), which Claude Code applies in every permission mode. Its reason names the role, says what
the role may run, and says that tests, linters and other tools are run by the orchestrating skill, not
by a review lens, which verifies by reading (`git show <base>:<path>`, `git log`, `git blame`). The
only parts of the command it repeats are a short, secret-redacted excerpt (`guardrails.redact_secrets`)
of the word it refused. With diagnostics on, a refusal is recorded as a `block` with its rule id.

**Failure.** It fails closed for the roles it holds. A payload that does not parse names no role
and exits 0 with no output, as every hook here does, and any caller that is not a held role exits
before the library is imported. Once the payload names a held role, any error (a failed import, a
path that cannot be encoded, a bug) refuses the call, is recorded, and is announced once per session
as a crash that failed closed, naming the exception's type only. A hook that cannot start at all,
or times out, fails open, silently: that is Claude Code's handling of a hook failure, which is why
this is hook-reachable code under the Python 3.9 floor and `dev/hook_smoke.py` runs it. Where
`/usr/bin/env` does not exist, the rewritten command fails to start: closed, at the cost of
availability.

## Design notes

- **Deterministic, not LLM-judged** — blocking must be fast and predictable; the classifiers are
  tested deny-lists, conservative by design to avoid friction (the roadmap's stated risk).
- **Reuse** — the test-gate reuses by-stack (`stacks.py`); budgets use a session-scoped counter
  file; logging reuses the redaction in `guardrails.py`.
- **Exit-code contract** — `2` = block (reason on stderr, fed back to the model); `0` = allow. A
  non-blocking warning (budget soft cap, the merge preflight's warnings and fail-open notice, the
  PR-created notice, a dropped
  config) is JSON on stdout — `systemMessage` for the operator plus
  `hookSpecificOutput.additionalContext` for the model (`diagnostics.hook_notice`). Never stderr:
  Claude Code discards a hook's stderr on exit 0, and two of these warnings reached nobody for
  months (ADR 0094).

## Scope: an accident-guard, not an adversarial sandbox

The security deny-list and secret redaction stop **unambiguous hazards and accidental leaks**, not
a determined adversary. Known, accepted limits:

- **Bypassable by obfuscation.** `sh -c` payloads and `$(…)`/backtick substitutions are re-classified
  recursively (ADR 0054), but a substitution whose *download output becomes the program*
  (`bash -c "$(curl …)"` — no pipe, nothing dangerous in the literal text), a wrapper flag that
  takes a separate argument (`sudo -u root rm …` — the flag's argument masks the command word),
  remote execution (`ssh host 'rm …'`), and a bare `git push --force` with no explicit target (the
  destination branch isn't knowable from the command string) are not caught. The list errs toward
  *allow* to avoid friction.
- **The test-gate runs repo-local code by design.** `commit_gate` executes the project's own
  `dev/validate.py` (or the stack lint) from the session `cwd`; the trust boundary is Claude
  Code's `cwd`, not the hook. Don't point a session at an untrusted repo and then commit. The git
  reads that narrow it (ADR 0101) disable `core.fsmonitor`, refuse a directory merely shaped like a
  repo, compare no file content, and get an allowlisted environment.
- **Role scope is the one allowlist.** Unlike the deny-lists above it refuses what it does not
  recognise, and it is meant to hold against content written to mislead a lens. Its limits: it holds
  only while the hook runs (a hook that fails to start or times out fails open); Read, Grep and Glob
  read anything the user can, so a lens talked into it could quote a secret into its findings (they
  cannot be confined to the repository, since the skills pass large diffs through scratch files
  outside it); on git older than 2.44, read-only git in a partial clone may fetch missing objects
  from the user's configured remote; on git older than 2.41, a checkout's `.gitattributes` can select
  a clean filter the user's config defines, and that version is the one on the hook's `PATH`, which
  can differ from the shell's; `env -u` was run here only with GNU `env`, and the macOS
  BSD form is unverified; `env` finds `git` through `PATH`, so a relative `PATH` entry could resolve
  `git` from the reviewed checkout, an exposure the main session's own Bash calls share; if another
  hook also returns `updatedInput` for the same call, which one Claude Code applies is unverified,
  and if it is the other one the command runs without this hardening, though it passed the checks
  on its text; `architect`'s Write no longer reaches skill definitions or anything outside `docs/`,
  but it may still overwrite any Markdown document under `docs/`, which this plugin's own repository
  uses for its design documentation, and in a repository whose pytest runs `--doctest-glob='*.md'` a
  document it writes there can run code when the tests next run;
  and a session started as one of these roles (`claude --agent agentic-forge:reviewer`) is held to
  that role's scope too.
- **Redaction covers common token shapes** (`sk-…`/`sk-ant-…`, `gh*_`/`github_pat_`/`glpat-`,
  AWS/Google/Slack keys, JWTs, `user:pass@` URLs, Bearer/Authorization, `KEY=value`) but is not
  exhaustive — treat `audit.jsonl` as sensitive and keep it out of shared locations.

## Eval model

- `guardrails.py` unit-tested on allow **and** block (100% line+branch); each hook script tested
  (block → exit 2, allow → exit 0, internal error → fail-open exit 0); `hooks.json` validated.
  mypy covers `plugin/hooks`.

## Beyond the hooks (shipped separately)

**Scheduling** (headless/CI cadence — knowledge-base re-scan, deploy-watch digests) and
**observability** (the audit-log digest) are not guardrails, so they live outside L4 — now
**built** in `schedule.py` / `observability.py` + the `run_scheduled` / `audit_digest` CLIs + a
cron workflow ([ADR 0024](decisions/0024-stage7-scheduling-observability.md)). A richer
observability dashboard remains an optional follow-on. L4 itself = the hooks listed above.
