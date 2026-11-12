# ADR 0106 — The read-only roles are held by a hook, not by their tool list

Status: Accepted (implemented)
Date: 2026-11-11

Corrects a claim in [0009](0009-engine-roles-and-handoff.md) (engine roles) and the role files: that `reviewer` and
`security-engineer` are read-only because their frontmatter says `tools: Read, Grep, Glob, Bash(git diff:*)`. Extends
[0019](0019-l4-guardrails.md) (the guardrail hooks).

> **Amended 2026-11-12 by [ADR 0110](0110-the-field-queue-items-7-to-15.md):** outside `docs/` the architect may also write `tech-design.md` into an existing slug-named feature folder and ADR records into its `adr/`/`adrs/`/`decisions/` or an existing ADR-series directory; every earlier refusal stays.

## Context

A field report, sent privately, counted 813 Bash calls made by `reviewer` and `security-engineer` lenses over four
days: `git log`, `git show`, test runs, `docker ps`, file writes. None was a bare `git diff` and none was refused. The
reporting session ran in `bypassPermissions`, so the report alone could not say whether the specifier was ignored or
whether the permission mode overrode it.

Measured on Claude Code 2.1.322, with a throwaway repository, the plugin loaded by `--plugin-dir`, no user or project
settings (`--setting-sources ""`) and `reviewer` spawned through the Agent tool:

| Command run by the `reviewer` subagent | `default` mode | `bypassPermissions` |
| --- | --- | --- |
| `git diff --stat` | ran | ran |
| `git log -1`, `git show HEAD:a.txt` | ran | ran |
| `python3 -c "print(6*7)"` | refused: "This command requires approval" | ran |

The refusal in `default` is Claude Code's ordinary permission check, the same one the main session gets, and it
treats read-only git as safe. The `(git diff:*)` specifier in a plugin agent's `tools:` restricts nothing: the agent
gets Bash. What kept the roles read-only was their prompt, and in `default` mode the session's permission prompts.
In `bypassPermissions`, the mode a fleet of headless sessions tends to run in, nothing did. A lens reads untrusted
content by design (the diff under review, a PR from someone else), so a lens that will run whatever a diff talks it
into is the case the boundary existed for.

The same probe captured the `PreToolUse` hook payload. A tool call made inside a subagent carries `agent_type`
(`"agentic-forge:reviewer"`) and `agent_id`; one made by the main session carries neither. A plugin hook can therefore
tell which role is calling, and a hook's `deny` applies in every permission mode.

## Decision

**1. A `PreToolUse` hook enforces the read-only roles, by allowlist.** `plugin/hooks/scripts/role_scope.py`, backed by
`agentic_forge.role_scope`, runs on every tool except Read, Grep and Glob (section 5). When `agent_type` names one of
the plugin's read-only roles it decides by that role's allowlist; for every other caller, the main session included,
it allows and stays silent.

- `reviewer` and `security-engineer`: Read, Grep, Glob, and Bash only for a single, simple `git` command with a
  read-only subcommand (`diff`, `show`, `log`, `status`, `blame`, `ls-files`, `ls-tree`, `rev-parse`, `merge-base`,
  `cat-file`, `grep`, `shortlog`, `describe`). Bash is refused when the command has a shell operator, a substitution, a
  redirection or a newline, a global option other than one `-C <path>` and `--no-pager`, or an option that writes a
  file, runs a configured program or leaves the repository (`--output`, `--ext-diff`, `--textconv`, `-c`,
  `--exec-path`, `--no-index` and their forms). Because the shell and git act on more than the literal words, the
  check is stricter than that list: every `$` form, every backslash, any unquoted glob, brace, grouping or `^`
  character, and an unquoted `=` that starts a word are refused (each is something bash or zsh can expand or read
  differently from the hook, so the hook could not see the result), and an abbreviation of a forbidden long option is
  refused, as are `--filters` and `--help`, which also run programs, `--show-signature` and any signature
  placeholder, with or without a modifier (`%`, then `+`, `-` or a space, then `G`; both run gpg, and both are a
  second layer under the gpg settings in section 2), a `--pretty=`/`--format=` name that is not a built-in format (a `pretty.<name>` alias
  from config could hold such a placeholder), and `--submodule` in every form (its `diff` form starts nested diffs that
  do not inherit `--no-ext-diff`). `--text` passes only where git's man pages list it as its own option (`diff`,
  `show`, `log`, `grep`); elsewhere git reads it as an abbreviation of `--textconv`. `cat-file` takes only `-p`, `-t`,
  `-s` and `-e`: its other options run textconv or filters, or read object names from stdin, which a lens cannot
  supply, so `--batch-check` is refused too. A `-C` path must be a working tree of the
  session's own repository (its checkout, a linked worktree or a submodule): git reads the config of the repository it
  is pointed at, and a directory with a repository's shape can arrive inside a reviewed change. Membership is read from
  git's own metadata, the `commondir` file a linked worktree's git directory holds, never from a directory's name: a
  first version took `<x>/worktrees/<name>` and `<x>/modules/<name>` as parts of `<x>`, so an ordinary checkout in a
  folder named `worktrees` counted as part of its parent and `-C` reached an unrelated sibling. There may be one `-C`
  (git resolves each relative `-C` from the one before), it may not contain `~` (a quoted tilde reaches git
  literally, so expanding it would check a different directory), and it is resolved as git's `chdir` resolves it,
  with no expansion.
- Matching is on the namespaced `agent_type` only (`agentic-forge:reviewer`). A bare `reviewer` is a project's or a
  user's own agent, which this plugin must not restrict; a test pins the namespace to the manifest's `name`.
- `grader`: Read, Grep, Glob.
- `architect`: Read, Grep, Glob, and Write for design documents only, by allowlist, as its contract needs. The resolved
  path (relative to the session's `cwd`, links followed) must lie under `docs/` of a working tree of the session's
  repository (its checkout or a linked worktree, found by the same walk as `-C`; not a submodule or a nested
  repository), end in `.md`, have no segment below that tree's top that starts with `.`, and not be named
  `CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md`, `GEMINI.md` or `SKILL.md` (case-insensitively). That leaves out the
  user's shell and git configuration, `.mcp.json`, `~/.claude.json`, `.claude/agents/`, the agent instruction files,
  skill definitions and any non-document, all of which a first blocklist missed. `docs/` is the role's contract
  directory: the `architecture` skill has it write `docs/sdlc/<slug>/*.md`, in the feature's doc-delivery worktree, a
  linked worktree beside the repository, and no skill sends it anywhere else. A later change may widen this to a
  repository's own feature folders, with its own detection. A `..` that leaves one working tree for the hidden space
  around another (where linked worktrees and `.git` live) is refused as outside the session's working trees. The
  blocklist stays as a second layer: a path, as given or resolved, with a `.git` component, or that is
  `.claude/settings*.json` or `.agentic-forge/config.json`, case-insensitively.
- Any other tool, an MCP tool included, is refused for these roles.
- The refusal says what the role may run, and that tests and tools are run by the orchestrating skill, not by a lens.

**2. What runs is what was checked.** A check on the command text can only be as good as its model of the shell, and
two shells (bash and zsh, with the user's options) read some text differently from `shlex`. So an allowed git call is
not passed through. The hook answers with `permissionDecision: "allow"` and an `updatedInput` whose `command` is
rebuilt from the words it checked behind a fixed hardening, every word single-quoted (the prefix too), so neither
shell expands anything in it, whatever its options (zsh's `MAGIC_EQUAL_SUBST` rewrites a bare word with `==` in it):

    /usr/bin/env -u <each variable below> GIT_NO_LAZY_FETCH=1 git -c safe.bareRepository=explicit
        -c core.fsmonitor=false -c core.hooksPath=/dev/null -c diff.submodule=log -c log.showSignature=false
        -c format.pretty=medium -c core.attributesFile=/dev/null -c gpg.program=/dev/null
        -c gpg.ssh.program=/dev/null -c gpg.x509.program=/dev/null --no-pager [--attr-source=<empty tree>]
        [-C <the resolved absolute path>] <subcommand> <hardening flags> <the checked arguments>

- Command-line `-c` outranks every config file, an included one too, and git hands it to the git processes it
  starts, in submodules as well. So no implicitly found bare repository, fsmonitor program or hook runs; a submodule's
  change is shown as a log, never as a nested diff; no signature is verified (`log.showSignature`, or a default
  `format.pretty` holding `%G`, would run `gpg.program`), and every signature program (`gpg.program`,
  `gpg.ssh.program`, `gpg.x509.program`) is `/dev/null`, which cannot run, so a placeholder the check misses still
  runs nothing; and no global attributes file is read. `--no-pager` runs no
  pager.
- `--attr-source=4b825dc642cb6eb9a060e54bf8d69288fbee4904`, the empty tree, which every SHA-1 repository has without
  storing it, makes git read no `.gitattributes` from the checkout, so a reviewed change cannot select a clean or
  process filter, a diff driver or textconv. The option arrived in git 2.41.0 (its release notes; 2.40 lacks it). The
  hook asks `git --version` once per call (3 s timeout), of the `git` its own `PATH` finds and only by an absolute
  path (a relative `PATH` entry could find one in the checkout), and adds the option on 2.41 and later, and also when
  the version cannot be told, since a git that rejects the option fails to start rather than running without it. The
  hook's `PATH` can differ from the Bash tool shell's: if the hook finds 2.41 or later and the shell runs an older
  git, that git rejects the option and the call fails closed; if the hook finds an older git and the shell runs 2.41
  or later, the option is left out and that call carries the old-git residual below. A SHA-256 repository does not know this id, so git refuses
  to start there; that fails closed. On git older than 2.41 the hook leaves the option out and does not refuse:
  `git diff` and `git status` are a lens's main input, and git 2.39 is still what Apple's command line tools, Debian 12
  and older Ubuntu releases ship, so refusing would stop reviews there. The residual on old git is that a checkout's
  `.gitattributes` can select a clean filter the user's own config defines (Git LFS is the common one), which `status`,
  a diff against the worktree, `blame` of a worktree file or `describe --dirty` runs on the checkout's content: the
  user's configured program, as it would run for the user's own `git status`.
- `GIT_NO_LAZY_FETCH=1` stops git 2.44 and later from fetching missing objects in a partial clone; older git ignores
  it, and a lazy fetch there uses the transport the repository's config names.
- The hardening flags turn off a configured external diff program and textconv filters where the subcommand takes
  them, as confirmed against git 2.43: `--no-ext-diff --no-textconv` for `diff`, `show` and `log` (their man pages),
  `--no-textconv` for `blame` (`git blame -h`) and `grep` (its man page). The other subcommands take neither and run
  neither program. A user's `--ext-diff` or `--textconv` would come after them and win, which is why those stay
  refused by the check.
- `env -u` clears the variables that point git at another repository, index, object store, attribute source or
  config (`GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR`, `GIT_INDEX_FILE`, `GIT_OBJECT_DIRECTORY`,
  `GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_NAMESPACE`, `GIT_ATTR_SOURCE`, `GIT_CONFIG*`), that name a program
  (`GIT_EXTERNAL_DIFF`, `GIT_PAGER`, `PAGER`, the editors, `GIT_EXEC_PATH`, `GIT_SSH*`, `GIT_ASKPASS`, `SSH_ASKPASS`,
  `GIT_PROXY_COMMAND`), or that name a file git writes (the `GIT_TRACE*` targets and `GIT_REDIRECT_*`), from `git help
  git`. `GIT_CONFIG_KEY_<n>` needs `GIT_CONFIG_COUNT`, which is cleared. `/usr/bin/env` is named by path, so no alias or
  shell function stands in for it, and it starts `git` from `PATH` with no shell in between.
- The check on the raw text stays, as a second layer: it is what refuses, and it is all there is if a Claude Code
  version ignored `updatedInput`.
- A command that already has this form (a model may send the rewritten command back) is checked as the plain command
  it came from and rewritten to the same text.

The contract, from the Claude Code hooks reference (<https://code.claude.com/docs/en/hooks>, "PreToolUse decision
control", read 2026-11-11): the output is `{"hookSpecificOutput": {"hookEventName": "PreToolUse",
"permissionDecision": "allow", "permissionDecisionReason": "…", "updatedInput": {…}}}`. `updatedInput` "replaces the
entire input object", so the hook copies the call's other fields (`description`, `timeout`, …) and drops only
`dangerouslyDisableSandbox`. Permission rules are evaluated "against the input your hook returns, not the input Claude
sent"; deny and ask rules "are still evaluated regardless of what the hook returns". `"allow"` "skips the permission
prompt, except for actions no mode auto-approves and reads from network paths". With no `permissionDecision`, auto mode
can deny the changed call because its server-side review saw the original, so the hook always pairs `updatedInput` with
`allow`. Read-only git was approved without a prompt in `default` mode already (the table above), so `allow` grants
nothing new. The contract is taken from the reference; it was not re-measured in a live session for this change.

The choice between `env -u` and refusing while a variable is set: the hook's own environment is Claude Code's, but the
shell a Bash call runs in also reads the user's shell startup file and `CLAUDE_ENV_FILE` (tools reference, "Bash
tool"), which the hook never sees, so a check of the hook's environment would miss variables set there. Refusing would
also stop every review for a user who exports `GIT_PAGER`, which is common. `env -u` clears them whatever set them,
and GNU, BSD (macOS) and BusyBox `env` document `-u`, though POSIX does not. The cost is a long command line in the
transcript.

**3. It fails closed for the roles it holds.** A payload that does not parse names no role and exits 0 silently, as
every hook does. Once `agent_type` names a held role, any error (a failed import, a path that cannot be encoded, a lone
surrogate, a bug) refuses the call, records the crash in the diagnostics log and says once per session that the hook
failed closed; the notice names the exception's type only, since its text can repeat the command. Every other caller,
the plugin's own other roles included, exits before the library is imported, so nothing in it can fail for them. The
script keeps its own copy of the held roles for that exit and for a failed import (a test keeps it equal to the
library's). A hook that cannot start
at all, or that exceeds its timeout, still fails open: the reference says a timed-out `PreToolUse` command hook "doesn't
block the tool call", and a hook that fails to start is a non-blocking error.

**4. The role files say what holds them.** `reviewer.md` and `security-engineer.md` keep `Bash(git diff:*)` as
documentation and say the hook enforces the scope; `grader.md` and `architect.md` say the same briefly. A test keeps
each role's `tools:` line equal to the hook's allowlist for it. The README and `guardrails.md` say the boundary holds in
every permission mode, and that a hook that fails to start fails open, as every hook does.

**5. The matcher reaches every tool but the read tools.** An allowlist reached through a list of tool names refuses
nothing that is missing from the list, and the first list missed MultiEdit, Monitor, PowerShell, Skill, SlashCommand
and the MCP resource tools. The reference says a matcher with characters other than letters, digits, `_`, `-`, spaces,
`,` and `|` is "a JavaScript regular expression, unanchored", tested with `RegExp.prototype.test`, which supports
lookahead, so the matcher is `^(?!(?:Read|Grep|Glob)$).*`: every tool name, present or future, but those three exact
ones. It matches Monitor itself, so per the reference the hook gets the Monitor call's own input and its `deny`
applies. Measured on this change's machine (WSL2, CPython 3.12, median of 30 runs of the script): 26 to 30 ms per call
for a caller that is not held, of which about 20 ms is starting the interpreter, since the script loads only `json` and
`sys` before that exit; 70 ms for a held role's allowed git call, which also asks `git --version`; 137 ms for a refusal,
which loads the diagnostics module.

**6. The skills stop asking lenses for what the role cannot do.** `code-review` and `deep-review` keep verification
in the orchestrating session, which has the stack's tools (step 3, "verify each finding"). A lens verifies by reading:
`git show <base>:<path>`, `git log`, `git blame`.

## Alternatives

- **State that the boundary is prompt-only and change nothing else.** Honest, and it was the fallback if the payload
  had not identified the role. It leaves a lens that reads attacker-written text able to run anything in
  `bypassPermissions`, which is the mode the fleet that found this runs in.
- **Remove Bash from the lenses.** `git diff` is their main input; without it, the orchestrator must paste every diff,
  which the skills already do for large ones but not for small.
- **Allow the stack's test command in a scratch copy.** Tests run repository code, which is not read-only by any
  definition the hook can check. The orchestrating skill already runs the tools.
- **Check the text and pass the command through (the first version of this hook).** Review found that every gap
  between the hook's model of the shell and the shell (backslashes inside double quotes, zsh's extended globbing, a
  quoted tilde, stacked `-C`) let a checked command run as a different one, and that git runs configured programs
  without any option asking for them. Closing those one by one leaves the next one open; executing the checked words
  closes the class.
- **On git older than 2.41, refuse the subcommands that can run a clean filter.** That is `status`, `diff` against the
  worktree, `blame` and `describe --dirty`, the lens's main input, on the git that Apple, Debian 12 and older Ubuntu
  releases ship. The residual it would close runs a program the user configured, on content the user checked out; not
  taken (section 2).
- **Keep a blocklist for the architect's Write.** Review found seven places a blocklist missed, from shell rc files to
  `.claude/agents/`; any list of what an agent must not write lags the places that run code. The allowlist states what
  the role is for. The blocklist stays under it.
- **Refuse while a git variable is set, instead of `env -u`.** Simpler to state, but blind to the variables the Bash
  tool's shell adds, and it would stop reviews for users who set a pager (section 2).
- **`"onFailure": "block"` on the hook entry** (Claude Code 2.1.295 and later). It would make a hook that cannot start
  or times out refuse the call, but it applies to every caller the matcher reaches, the main session included: a
  missing `python3` would stop every tool but the three read tools in every session. Not taken; worth revisiting if
  Claude Code can scope a hook to an agent type.
- **Matcher `*` with an early exit.** Equivalent coverage; the lookahead also spares the three read tools a Python
  start each, and the reference confirms the regex form.

## Consequences

- A prompt that asks a lens to run tests, scripts or docker now gets a refusal it can read. A fleet that relied on
  lenses doing that moves the step to the orchestrating session.
- Turned off for a lens's git call: an external diff program, textconv, the pager, hooks, fsmonitor, nested submodule
  diffs, signature verification and every gpg program, the global attributes file, implicitly found bare
  repositories, the git variables
  from the environment that redirect git or name a program or a trace file, and, on git 2.41 and later, every
  attribute the checkout sets; on git 2.44 and later, lazy fetching. Not turned off: the residuals below. A lens that
  wants an unquoted `HEAD^` gets a refusal; `'HEAD^'` or `HEAD~1` works.
- An architect that is asked to write anything but a Markdown document under the repository's `docs/` gets a refusal.
- The read-only contract of `reviewer` and `security-engineer` holds against a diff that talks the lens into writing,
  in every permission mode, as long as the hook runs. A hook that fails to start fails open: it is hook-reachable code,
  so Python 3.9 and `dev/hook_smoke.py` apply. An error inside it, for a held role, refuses.
- The decline of an MCP-tool wildcard for these roles (field thread ac73157d) stands, now on an enforced boundary:
  the hook refuses every MCP tool for them.
- The hook runs on every tool call but Read, Grep and Glob, including the main session's, where it exits after parsing
  the payload. Its cost there is one Python start and a JSON parse (section 5).
- Residuals, stated and not fixed:
  - Read, Grep and Glob read whatever the user can read, so a lens talked into it by injected text could quote a
    secret into its findings. They cannot be confined to the repository: the skills hand large diffs to lenses through
    scratch files outside it.
  - On git older than 2.44, read-only git in a partial clone may fetch missing objects from the user's configured
    remote, over the transport the user configured for that repository.
  - On git older than 2.41, a checkout's `.gitattributes` can select a clean filter the user's config defines, which
    `status`, a worktree diff, `blame` of a worktree file or `describe --dirty` runs (section 2 has why this is not
    refused). Attributes in `$GIT_DIR/info/attributes`, which a checkout cannot write, apply on every version.
  - Other programs the repository's own config names, for purposes these subcommands do not reach with the refused
    options and the forced settings above, run as they would for the user.
  - The rewritten command starts `/usr/bin/env` by path. Where it does not exist the call fails, closed; that costs
    availability only.
  - `env -u` is documented by GNU, BSD (macOS) and BusyBox `env`, not by POSIX, and it was run here only with GNU
    `env`; the macOS form is unverified.
  - `env` finds `git` through `PATH`. A relative `PATH` entry (`.` or `bin`) could resolve `git` from the reviewed
    checkout; the main session's own Bash calls have the same exposure.
  - If another hook also returns `updatedInput` for the same call, which one Claude Code applies is unverified. If the
    other one wins, the command runs without this hardening, though it has still passed the checks on its text.
  - The architect may still write any Markdown document under `docs/`, including one a test runner executes: pytest
    with `--doctest-glob='*.md'` collects doctests from Markdown files, so in a repository that configures it, a
    document the architect writes can run code when the tests next run.
  - The version check asks the `git` on the hook's `PATH`, which can differ from the shell's (section 2).
  - A session started as one of these roles (`claude --agent agentic-forge:reviewer`) carries that `agent_type` on
    every call and is held to the role's scope too.
