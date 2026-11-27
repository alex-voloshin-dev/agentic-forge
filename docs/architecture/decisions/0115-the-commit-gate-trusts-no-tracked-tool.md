# ADR 0115 — The commit gate trusts no tracked tool

Status: Accepted (implemented)
Date: 2026-11-24

Amends [0081](0081-field-bundle-2026-09-batch.md) (§5, the gate resolves its tool the way the project does) and
[0101](0101-the-commit-gate-only-narrows.md) (its Limits: "A tracked `.venv/bin/ruff` runs as it did … A follow-up ADR
is planned"; this is that ADR).

> **Amended 2026-11-27:** the narrowing's own git reads (`gate_scope`) now run git by the absolute path the same lookup
> finds, closing the first limit below. See [the amendment](#amendment-2026-11-27-the-narrowings-git-reads-use-the-same-lookup).

## Context

ADR 0081 made the commit gate resolve its tool project-first. The hook lists the existing `node_modules/.bin`,
`.venv/bin`, `venv/bin`, `.venv/Scripts` and `venv/Scripts` at the commit's directory and at the main repo root,
takes argv[0] from the first of them that holds it, and puts all of them in front of the gate's `PATH`, so a package
script's own `eslint` resolves too. The field case was real: 50 of 69 fail-opens were a linter that lived only in a
virtualenv or in `node_modules/.bin`.

Two facts about the hook make that resolution a trust problem:

1. **The gate is a `PreToolUse` hook.** It runs when a session *tries* `git commit` or `git push`, before the user's
   permission prompt for that command. Declining the commit does not undo the gate run.
2. **The gate inherited the hook's whole environment**: `GH_TOKEN`, `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`,
   cloud keys, an SSH agent socket, whatever the session had.

An installed virtualenv or `node_modules` is never committed: they are generated, platform-specific and gitignored
by every template. A *tracked* tool directory is content the repository's authors chose to ship, not the user's
installed toolchain. With the old resolution a program in one ran, with the session's environment, as soon as a
session attempted a commit in a freshly cloned repository, whether or not the user then approved the commit. ADR
0101 recorded this as a known limit and deferred it here.

The repository's own *declared* checks are a different matter. `dev/validate.py`, a `lint` script in `package.json`,
a project ruff config: those are the project's code, run under the workspace trust the user granted when they opened
the folder, and running them is what the gate is for. This ADR does not change that (see Limits).

## Decision

Everything below is in `plugin/lib/agentic_forge/guardrails.py` and `plugin/hooks/scripts/commit_gate.py`. What
changes, exactly:

- the hook no longer takes argv[0] from, or adds to the gate's `PATH`, a tool directory git tracks anything in;
- a package-script gate (`npm run lint`) is not run at all when a `node_modules/.bin` its package manager would put
  on the script's `PATH` is such a directory;
- the gate's environment carries no credential-named variables;
- the gate's program runs by absolute path.

The project's declared checks still run.

### 1. A tracked tool directory is not used

`guardrails.bin_dirs(cwd)` reads the directories once per hook run, within one 2-second budget, and returns a
`BinDirs`. `trusted` holds the existing directories git tracks nothing in. `skipped` holds the others, each with a
reason: `BIN_DIR_TRACKED` ("tracked by git") or `BIN_DIR_UNCHECKED` ("could not be checked with git"). The hook passes
that one `BinDirs` to `resolve_gate` (argv[0]), `gate_env` (the `PATH` prefix) and the notice, so they cannot
disagree, and git is asked once per directory. `gate_bin_dirs(cwd)` still returns the trusted list.

The check (`_bin_dir_doubt`) asks the repository the directory really belongs to:

- every path component from the work-tree top (`git rev-parse --show-toplevel`, asked once per root) down to the
  directory must be listed by `os.listdir` with exactly that spelling; outside a checkout, the components of the
  name. On a case-insensitive filesystem `.venv/bin` opens a tracked `.VENV/bin`, and `svc/.venv/bin` a tracked
  `SVC/.venv/bin`, neither of which `ls-files` of the name as written lists. The parent walk of §2 checks each
  parent's components the same way. git's top and the hook's root are compared as paths of the host's flavour,
  both resolved (`_parts_below`: `relative_to`, a `ValueError` is doubt), never as strings: git on Windows prints
  `C:/x/y` where the hook has `C:\x\y`, and a Windows path ignores case;
- `git --literal-pathspecs ls-files -z -- .` runs **inside the directory's real path**, so a submodule or a nested
  repository answers for itself, and a directory reached through a link is judged where it lives;
- for each component of the name that is a symbolic link, `git ls-files -z -- <component>` runs from the root. git
  lists a tracked link as one entry and nothing through it, so listing the directory alone would miss a committed
  link to a tracked directory.

Any output means tracked. The reads use the hardened pattern `commit_dir` already uses (`_git_bytes`): git by an
absolute path, `gate_scope._GIT`'s hardening flags (`core.fsmonitor=false`, …), the minimal `_READ_ENV` allowlist,
`GIT_NO_LAZY_FETCH=1` and stdin from `/dev/null`.

**Outside a checkout nothing is tracked**, so the directory is used as ADR 0081 has it. "Outside" is decided without
git: no `.git` (directory, file or link) at the directory or above it. A host with no git, and a virtualenv linked to
a location outside the repository, keep working.

**Doubt is distrust.** Inside a checkout, any of these skips the directory:

- a different spelling on disk, or no work-tree top from git;
- no `git` by an absolute path;
- a non-zero exit, a timeout, an exhausted budget or an `OSError`.

argv[0] then resolves from the remaining trusted directories and `PATH`. If it is not there, the gate fails open with
its existing notice.

**This holds only for what the hook itself resolves.** A declared check can still call a tracked tool on its own:
`dev/validate.py` could run `.venv/bin/ruff` by path. That is the project's code (see Limits).

### 2. A package script is not run beside an untrusted `node_modules/.bin`

npm, pnpm and yarn rebuild the script's `PATH` themselves: `npm run lint` prepends the `node_modules/.bin` of the
package and of every parent directory. So the hook cannot keep a tracked one out of the script's lookups.

When the gate's program is a package manager (`stacks.PACKAGE_MANAGERS`; in practice the gate only ever runs
`npm run lint`), `bin_dirs(cwd, package_script=True)` also reads the `node_modules/.bin` of `cwd` and of every parent
(`script_skipped`). If any of them is skipped as tracked or unchecked, the gate is **not run**. The commit goes
through ungated (fail open) and the hook:

- records an `anomaly`;
- prints a notice on stderr;
- tells the operator in `systemMessage` that `npm run lint` was NOT run and why, naming the directory, with the
  remedies: make sure git tracks nothing in it, or `test_gate.skip`.

A real-npm test shows the threat (a direct `npm run lint` does run a tracked `node_modules/.bin/eslint`) and the
remedy (the hook never does).

### 3. The user is told, once per session per set

When the hook ignores a directory, it builds one line naming each skipped directory and its reason. That line says
exactly what changed: the hook neither takes the gate's program from the directory nor adds it to the gate's `PATH`,
and the project's own checks still run. It goes to stderr on every run, which is the model's channel when the commit
is blocked.

The operator gets it in the run's `systemMessage`, with a pointer to `test_gate.skip` for an untrusted repository.
That message is shown **once per session per set of skipped directories**. `diagnostics.once_per_session` keeps one
fixed key per kind (`commit-gate:untrusted-tools:dirs`, `…:script`) whose value is the session and a digest of the
sorted set, so the same set does not repeat on every commit, a new set is news, and the notices file does not grow
with each set. A hook prints one
JSON object per run, so the line joins the fail-open or skip notice when there is one.

stderr alone would not do: stderr from a hook that exits 0 reaches only the debug log (ADR 0081 §4).

### 4. No credential-named environment variables

`gate_env` drops every variable for which `looks_like_credential(name)` holds. The rule reads the name only. It is
split into words at every non-alphanumeric character and at camelCase humps (`authToken`, `APIKey`), then
upper-cased. A name is a credential when:

- a word is `TOKEN(S)`, `SECRET(S)`, `PASSWORD(S)`, `PASSWD`, `CREDENTIAL(S)`, `AUTH`, `APIKEY`, `PAT`, `PASS` or
  `DSN`;
- a word **ends in** `TOKEN`, `SECRET`, `PASSWORD` or `PASSWD` (`PGPASSWORD`, `GITHUBTOKEN`);
- a word is `PWD` in a name of two or more words (`MYSQL_PWD`; `PWD` alone is the working directory);
- the last of two or more words is `KEY` or `KEYS` (`OPENAI_KEY`, `SENDGRID_KEY`);
- two adjacent words are `API KEY`, `PRIVATE KEY`, `ACCESS KEY` or `SESSION KEY`;
- the name starts with `AWS_SECRET`;
- or the name is `KRB5CCNAME` (a Kerberos ticket cache).

Kept: `GIT_AUTHOR_NAME`, `TOKENIZERS_PARALLELISM`, `OAUTHLIB_INSECURE_TRANSPORT`, `PATH`, `HOME`, `PWD`, `LANG`,
`VIRTUAL_ENV`, `NPM_CONFIG_USERCONFIG`, `XDG_RUNTIME_DIR`, and `DBUS_SESSION_BUS_ADDRESS`: the desktop bus's
default socket under `XDG_RUNTIME_DIR` stays reachable without it, so dropping it would achieve little. Every case
is a test.

**Withholding a variable can make a gate block, not only fail open.** `go vet` that fetches a private module, or an
`.npmrc` that reads `${NPM_TOKEN}`, can exit 1 with output the fail-open signatures do not know. So when a gate
blocks, `guardrails.withheld_names()` names the withheld variables, **names only, never values**, the first 12:

- the operator's skip notice always names them and says `test_gate.skip` is the way to commit;
- the model's block message names them only when the gate's output reads like an authentication failure
  (`guardrails.looks_like_auth_failure`, by phrases a rule id or a path does not hold: npm's `code E401`/`code
  E403` and `ENEEDAUTH`, `HTTP 401` (with or without a version), `401 Unauthorized`, `403 Forbidden`,
  "authentication failed/required", git's "could not read Username" and "terminal prompts disabled", ssh's
  "Permission denied (publickey)"; not ruff's `E401` rule, not `app/authentication/views.py`). It then says such a
  failure is not a finding in the code and to ask the user.
  On an ordinary lint failure the hint would only distract. The model is still not told how to turn the guardrail
  off (ADR 0101's split).

### 5. The gate's program runs by absolute path, never from its directory

`guardrails.executable(argv, PATH)` looks a bare argv[0] up itself (`_find_program`). It reads only the absolute
entries of the gate's `PATH`, trying on Windows each allowed `PATHEXT` extension (and the bare name first when it
already has one), and the hook runs the absolute path it finds. `resolve_gate`'s `python` → `python3` fallback is
chosen by the same routine on the same sanitized `PATH`, so it picks only what will run.

**On Windows only an `.exe` or `.com` is run.** A `.bat`/`.cmd` runs through cmd.exe, which reads `& ^ % ( )` in its
arguments, and the narrowed gate passes repository file names as arguments (a file named `a&b.py`). So a batch shim
(pyenv-win, for one) is skipped in favour of a later `.exe`, and when only a script resolves the run fails open. The
one exception is a gate whose whole argv is fixed, with no word from the repository: `npm run lint` may run
`npm.cmd`. An argv[0] that is already a path to a script is refused the same way. It does not use `shutil.which`: on Windows that searches the current directory
first (on 3.9–3.11 always, on 3.12+ unless the *hook's* environment sets `NoDefaultCurrentDirectoryInExePath`). If
nothing resolves it raises `FileNotFoundError`, so `_run_gate` fails open with its notice **without starting any
process**. A bare name is never spawned, since the system's own lookup could search the current directory, which is
the repository.

`gate_env` drops empty and relative `PATH` entries, which name that directory too. When no absolute entry is left it
uses a fixed default, `/usr/bin:/bin` on POSIX or the system root's `System32` on Windows; never an empty `PATH` and
never `os.defpath`, which can start with an empty entry. On Windows it also sets
`NoDefaultCurrentDirectoryInExePath=1` for the gate's own lookups. What the hook shows (`resolve_gate`, the block
message) is unchanged: the tool's name, or its project-local path. A gate that names a path (`./gradlew`) is the
project's declared check and runs as written.

## Rejected alternatives

- **Check only the directory with `ls-files -- <name>` from the root.** A committed link `.venv` → a tracked directory
  lists nothing under `.venv/bin`; measured on git 2.43. Hence the real-path read plus the link components.
- **Distrust a directory that is merely inside a checkout.** That is every installed `.venv`, and would undo ADR 0081's
  field fix.
- **Strip the untrusted `node_modules/.bin` from npm's `PATH`.** npm builds that `PATH` itself after the hook hands
  over; the hook cannot reach it. Not running the script is the only reliable answer.
- **An allowlist of environment variables for the gate.** A linter, a package script and the interpreters they start
  need an open-ended set (`VIRTUAL_ENV`, `NODE_OPTIONS`, `PYTHONPATH`, proxies, locale, tool configs). A short
  allowlist would turn working gates into fail-opens. Dropping what names itself a credential removes the
  high-value environment secrets without that cost.
- **Drop the project-local resolution altogether.** It is the field fix of ADR 0081; the tracked case is the only one
  that is not the user's own toolchain.
- **Print the notice on stderr only, or on every commit.** stderr reaches the operator only on a block. A notice on
  every commit for the same directories becomes noise that hides the next one.
- **`shutil.which` on the absolute entries.** On Windows it still searches the current directory first unless the
  hook's own environment opts out, which the hook does not control.
- **Tell the model about withheld variables on every block.** Most blocks are ordinary findings, where a credential
  hint only invites the model to blame the environment.

## Consequences

- A repository that commits its tool directory (a vendored `node_modules` with its `.bin`, for example) gets its
  tools from `PATH`. A Python or Go gate fails open with the notice when the tool is not on `PATH`. A package-script
  gate is not run at all, with its notice.
- Each existing tool directory inside a checkout costs one `git ls-files` per hook run (more only through links), plus
  one per existing parent `node_modules/.bin` for a package-script gate.
- A gate that needed a credential from the environment now fails open or blocks. A block names the withheld
  variables. The remedy is `test_gate.skip`.
- Block messages and notices still name the tool as the project wrote it; only the executed argv[0] is absolute.
- Hook-reachable code, so it is Python 3.9-safe. `dev/hook_smoke.py` runs a commit in a repo with a tracked
  `.venv/bin/ruff` and a staged file, and CI runs it under 3.9. The planted tool must not run, `PATH`'s must, and no
  credential-named variable may reach it.

## Limits

- **The narrowing's own git reads run git by its bare name** (`gate_scope`, ADR 0101). On Windows, process creation
  searches the hook's current folder before `PATH`, so a `git.exe` committed there would run before the prompt, with only
  the `_READ_ENV` allowlist. This change does not touch that path; `guardrails`' own reads already use an absolute git.
  A follow-up resolves git once, absolutely, for `gate_scope` too. *Closed by the 2026-11-27 amendment below.*
- **No Windows run.** The Windows behaviour (path comparison, `.exe`/`.com` only, `npm.cmd` for the fixed argv) is tested
  with `PureWindowsPath` and a patched platform flag on Linux, not on a Windows host.
- **Credentials outside the environment remain reachable.** The gate runs as the user. Files under `HOME` stay
  readable: `~/.aws`, `~/.config/gh`, `~/.npmrc`, `~/.git-credentials`, SSH keys. So do a running SSH agent or keyring
  reached by other means, and a credential helper git or a package manager calls. This ADR removes credential-named
  environment variables only.
- **The project's declared checks still run before the prompt.** `python dev/validate.py`, `npm run lint` and a
  project ruff config are the project's own code. They run as before, under the workspace trust the user granted when
  they opened the folder, and can call any tool, a tracked one included. **For a repository you do not trust,
  `test_gate.skip: true` (or `AGENTIC_FORGE_SKIP_TEST_GATE=1`) is the real protection**, set before the session tries
  to commit. Opening an untrusted repository in a session that commits stays the user's risk, as `guardrails.md`
  says.
- **The credential rule reads names, not values.** A secret under an ordinary name (`DATABASE_URL` with a password in
  it) still reaches the gate.
- **A tool on `PATH` is trusted.** An absolute `PATH` entry that points into the repository, set by the user, is
  outside this decision.
- **Whether a directory is in a checkout is read from the filesystem.** No `.git` at or above it means trusted, with
  no git read. Where the walk sees a `.git` but git answers "not a repository" (a filesystem boundary,
  `GIT_CEILING_DIRECTORIES`), that is doubt and the directory is skipped: the safe side.

## Amendment 2026-11-27: the narrowing's git reads use the same lookup

`gate_scope._git` ran `git` by its bare name, the first limit above. It now runs the absolute path
`guardrails.executable(["git"], PATH)` returns: the absolute entries of the hook's `PATH` only, and on Windows a
`git.exe`/`git.com` only, so neither a `git` committed to the repository nor a `git.cmd` shim (cmd.exe would read
`& ^ %` in the pathspecs a read passes) can run. `gate_scope._git_program` caches the answer per `PATH` value, so a
hook run looks git up once, not once per read. No git found is a read that did not answer (`_GitFailed`), which
`narrow` already turns into the gate as it is: the whole gate runs, as on any other git failure. `_GIT` keeps its
leading `git` as a placeholder; `guardrails._git_bytes` already drops it and passes its own absolute git.

The other hook-reachable git runs already used an absolute path, found with `shutil.which` and refused when it was
relative: `guardrails.commit_dir`, the tool-directory check (`guardrails._bin_dir_doubt`),
`role_scope._git_version` and `merge_preflight._git_path`. On Windows `shutil.which` could still choose a `git.cmd`
from an absolute entry. That was recorded here as a follow-up; it is closed by the second amendment below.

## Amendment 2026-11-27 (2): every hook-reachable git and gh, and the PR CLIs, use the same lookup

The four sites above, and `merge_preflight._gh_path`, now call `guardrails.trusted_program(name)`: `_find_program`
on the hook's own `PATH`, the lookup `executable` uses, so absolute entries only and on Windows an `.exe`/`.com` only.
Not cached: each site looks up once per call, a few `stat`s, and `_git_version` is already cached per process.
`role_scope` already imported `guardrails`, so no import cycle or new module was needed. Nothing found keeps each
site's answer from before:

| Site | Nothing found |
| --- | --- |
| `guardrails.commit_dir` | the start directory |
| `guardrails._bin_dir_doubt` | `BIN_DIR_UNCHECKED`: the tool directory is skipped |
| `role_scope._git_version` | unknown, so `--attr-source` is added and an old git fails closed |
| `merge_preflight._git_path` | the local checks skipped, with their notice |
| `merge_preflight._gh_path` | the gate unavailable, failing open with its notice |

One behaviour changes on purpose. `shutil.which` stopped at the first entry holding the name, so a relative entry
ahead of an absolute one ended the lookup in a refusal. Now the relative entry is skipped, as the gate's own lookup
skips it, and a program on a later absolute entry is run. For the merge gate that means `gh` on a later absolute entry
is asked instead of the merge failing open. The relative-only case still fails open, now with "gh is not installed or
not on PATH by an absolute path". The separate "found through a relative PATH entry" message is gone.

The shipped CLIs that read GitHub from the repository directory, `af.py` (`_read_process`, `_read_raw`,
`_git_answers`) and `plugin/bin/pr_watch.py` (`_fetch`, the reply/resolve, permission, merge, merge-check, comment and
push calls and `_git`, all through one `_run`), ran `gh` and `git` by their bare names. There Windows searches the
current directory, which is the repository or the PR's tree, before `PATH`. They now run the absolute path
`guardrails.executable(argv, PATH)` returns, resolved when each command runs. The argv builders in
`agentic_forge.pr_watch` are unchanged, and so are the commands `af.py` prints for the session to run. Nothing found
raises the `FileNotFoundError` the bare name raised when missing, before any process starts, so every caller's handling
stays the same: `af.py` says "gh is not on PATH", a permission read is a no, unread comments are unknown.

Tested on Linux in the same Windows simulation as the gate (`_WINDOWS` patched, a `PATHEXT`). At each site a `.cmd`
on an absolute entry is never chosen and gets the nothing-found answer, and a later `.EXE` is the one started. A
relative entry is never run.

