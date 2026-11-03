# ADR 0104 — Skills run a shipped script, not inline Python

Status: Accepted (implemented)
Date: 2026-11-03

Closes the residual risk [0102](0102-a-checkout-does-not-choose-where-state-goes.md) recorded about the skills'
inline calls and the follow-up [0100](0100-external-reviewer-isolation-and-skip-reasons.md) recorded about the same
thing. Extends [0072](0072-shipped-cli-and-user-level-state.md) (runtime CLIs ship under `plugin/bin/`) and
[0094](0094-the-audit-the-same-three-shapes-everywhere.md) (the 3.9 floor reaches what a skill runs). Applies the rule
of [0045](0045-pr-watcher-1b.md) and [0103](0103-a-checkout-does-not-steer-the-watcher.md) on forks and on who
may reach a fixer to the path a session takes.

## Context

The skills told the model to run the library inline. Two separate failures came out of that one form.

**A checkout could run code as the user.** `python -c` puts the working directory first on `sys.path`, ahead of the
standard library. So a module committed to a repository took the place of the one the call imported, and its code ran
with the user's permissions when a skill's documented command ran. A security review reproduced this from a fresh clone,
and the security hook let the command through, correctly by its own rules, since nothing in the command line is
dangerous. The form in `pr-watch`, which inserts the library at the front of `sys.path` first, did not help: a
stdlib name planted beside it still ran, because the working directory stayed on the path.

**A plugin-only install could not run them at all.** `python3 -c "import agentic_forge"` raises
`ModuleNotFoundError` wherever the repo's package is not installed, and many machines have no `python`. The skills said
"installed module", and on a plugin-only install there is none. The `knowledge` skill then told the model to write the
note by hand, which skips the vault path rule of ADR 0102.

The inventory also found what a grep for `python -c` does not. Eight lines used the form:
`knowledge`, `repo-onboarding`, `release`, `deploy-watch`, `incident-response` and `pr-watch`, and the connector
references of `deploy-watch` and `incident-response`. `patterns/handoff.md` held an import in a Python block. And some
twenty skills, patterns and references named library calls in prose, such as
`handoff.load_artifact(<path>, expected_type="prd")`, with no way to run them other than the model writing its own
inline call. Replacing only the eight lines would have left that.

Measured on Python 3.12: run as a script, `sys.path[0]` is the script's directory, the working directory is not on the
path, and a `re.py`, `json.py`, `yaml.py` or `agentic_forge/` beside the working directory is not imported. Under `-c`
the same `re.py` runs.

A second review, of the flows and mostly of what was older than this script, found that the skill's order and
`push` could produce a wrong merge or push, and that a missing or mixed source could still read as healthy. Those are
12 to 14 below.

A review of the first version of this change found that a script alone was not enough, on four fronts: the interpreter
reads `PYTHONPATH` before a script's first line; git reads the config of any directory shaped like a bare repository;
the skill path had no rule about forks, or about a person's actual permission; and a skill told to run a printed `shell`
line "as written" could take its JSON escaping literally, which on a reviewer's apostrophe created a file in four
shells. All are closed below.

## Decision

**1. One shipped script, `plugin/bin/af.py`, run as `python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" <command>`.** CLAUDE.md
names that variable as what a skill may use. The script finds the library beside itself, so nothing has to be installed.

`-E` is part of the call, for this and for every shipped script a skill names. It makes the interpreter ignore
`PYTHON*`, and that has to happen on the command line: `PYTHONPATH=.` runs a planted `sitecustomize`, `encodings` or
`__future__` before any line of the script, so nothing the script does could stop it. A project's `.claude/settings.json`
`env` can set that variable. `-E` keeps user site-packages, which may hold PyYAML, where `-I` would not. So the script
holds no path scrub of its own: a first version had one, and it could only ever cover what was imported after startup.

**2. One narrow command per operation a skill needs, and no way to call anything else.** 21 commands, each with its own
flags: no generic dispatcher, no `eval`. A test holds the commands and every flag to what the skills and patterns
document, in both directions, so something nobody uses fails too.

| Area | Commands |
| --- | --- |
| Vault | `vault-validate`, `vault-scaffold`, `vault-recall`, `vault-add-note` |
| Handoff and review loop | `handoff-load`, `review-decision`, `review-blocks`, `plan-batches` |
| Stack | `stack-detect` |
| Release | `release-commits`, `release-summarize` |
| Operations | `deploy-status`, `alerts-active`, `incident-classify` |
| Pull requests | `pr-state`, `pr-merged`, `pr-reply-argv`, `pr-conflict-notice` |
| Document delivery | `doc-worktree`, `doc-proceed`, `doc-pr-argv` |

Resolving a review thread and marking a PR a draft stay literal `gh` lines in the skill, since a command would add nothing;
a test holds each to what the library builds. The external reviewer needed no command: `bin/external_review.py` was
already there and is what the skills now name. It imported PyYAML at the top, so it could not even start on a bare
`python3`, and now imports it for `--out` only.

`handoff.validate_header` has no command. It checked a dict, and ADR 0096 already said the file is what has to be
checked. `handoff-load` reads the file and runs the same schema, so "validate, then read back" is one call.

**3. A result is one JSON object on stdout.** Exit 0 is done. Exit 1 is a refusal, a failure, or a check that found
problems; a check still prints its JSON, and otherwise the reason is one line on stderr, capped, with control characters
removed, because a message can repeat a repo's text. Exit 2 is bad usage. Exit 3 is a missing package.

Values are checked where they arrive, because the library writes some of them straight into a path or a command: a
note's name and tags, a branch, a thread id, a repository slug. A file given to a command must be a regular file and not
a link, and is read through a cap, so a link to `/dev/zero` is refused at once. What goes out is walked within a budget,
charged per value and per character of a string.

**4. A command that changes something outside the process is returned, not run, and free text stays out of it.** A push,
a merge, a commit, a reply: the script prints `{"argv", "shell"}`, and the session runs `shell`, decoded from JSON first.
The guardrail hooks read the Bash command line and not what a script does inside it, so a merge through the script would
have gone past `merge_preflight`, and a commit past the test gate. Reads, `pr-state` and `pr-merged`, run `gh`
themselves. The vault's writes do run here, since no hook guards them and the vault's own rules are what protect them.

A reply and a PR body stay in a file (`gh api -F body=@<file>`, `gh pr create --body-file <file>`), so no reviewer's text
is on the line to be mangled or read by a shell. `gh` has no file form for a title, so a title is limited to characters
that mean nothing to a shell and need no escaping. `doc-proceed` prints the stage step as well as the commit, for the
artifact named with `--artifact`, because a commit takes only what is staged.

**5. Git does not read a directory that merely looks like a repository.** A checkout can commit a directory shaped like a
bare repository, config and all. Git run inside it reads that config, and `log.showSignature` with `gpg.program` then
runs a program of the repo's choosing: measured from `release-commits` after a real clone. So `af.py` adds
`safe.bareRepository=explicit` through `GIT_CONFIG_COUNT`, keeping whatever that already holds, and a printed `git` line
carries `-c safe.bareRepository=explicit`. A linked worktree of a bare clone works, because it has a `.git` file; a test
holds that. What breaks is running from a bare repository's own directory, which now fails and says so.

**6. A fork is read-only, and a person's association is not their permission.** `merge_readiness` has a `from a fork`
reason, and `plan_watch` gives a fork no threads. `pr-state` returns the `push` command itself, null for a fork or for a
branch name that is not one: the fact it depends on is in the same read. It also returns `merge`, null unless the gate is
open, merging is on for this repo, and the state is live, and pinned to the head that read saw. So there is no separate
command that prints a merge. In live mode `pr-state` asks GitHub about each person's permission, once per login, failing
closed, through `pr_watch.author_checker`, the logic the scheduled driver uses (ADR 0103). A `--snapshot` says
`"source": "snapshot"`, was checked with nobody, and never opens a merge.

**7. Without PyYAML or jsonschema, it says what it did not do, and the loop can exit.** Both stay optional and are
imported only where needed.

| Command | Without the package |
| --- | --- |
| `handoff-load`, `plan-batches` | Exit 3, naming the package and saying nothing was checked. The library alone would pass any header when `jsonschema` is missing (`validate_header` returns `[]`, which suits a hook), so the script checks first. |
| `vault-recall` | Works, ranks on names and bodies, and says under `warnings` that titles and tags were not read. |
| Everything else | Needs neither. |

Exit 3 means stop: status stays `in-review`, nothing is committed, the package is reported. In a review loop that is
`--gate-green unknown`, which escalates. With only `yes` and `no`, a phase on a stock `python3` would revise for ever on a
gate it can never turn green. Installing a package is the user's decision.

**8. Committed text cannot cost more than it should.** `frontmatter.parse` refuses a YAML alias, since no artifact needs
one and a few lines of them expand past memory. The `stack:` hint is matched a line at a time and read up to a cap: the
old pattern was quadratic on newlines, 100 KB took over a minute, and the commit gate reaches it.

**9. A failed read is not an empty answer.** `release.commits_since` used to answer `[]` when git failed, which reads as
nothing to release. It now raises when `git log` fails or a given tag does not resolve, and refuses a tag starting with
`-` wherever it came from, since git allows one to exist and `--output=` on a `git log` line writes a file. A repo with no
tag gives all of HEAD, as the skill's first step allows. `deploy-status` takes a whole recorded snapshot, or the live
pipeline with `--alerts-json`, and not a mix, since an alerts-only snapshot beside `--repo` read as no deploys and so as
healthy. A record for another environment is left out, and a file where all of them are is refused, naming them.

**10. A refusal from the vault is reported.** The `knowledge` skill's hand-write path and its frontmatter recipe are
gone. "Module unavailable" no longer arises, and a refusal is the vault doing what ADR 0102 asks. `repo-onboarding` says
the same. `vault._render_note` now quotes the title and tags, so `a: b`, `*x`, `true`, `123` and `2026-01-01` come back
as the strings they were, where a title with `: ` used to save with frontmatter nothing could read and lose its tags. Names
`moc` and `readme` are refused in any case, and so is replacing a `type: moc` file with a note.

**11. Tier-0 keeps it from coming back.** `validation.validate_no_inline_python` fails `dev/validate.py` on `python -c`
and its variants with other flags (`-Ic`, `-W x -c`, `-X y -c`), `python -`, `python <<`, `python /dev/stdin`, a pipe into a
bare `python`, `python -m agentic_forge`, an `import` or `__import__` of the library in any `.md` under `skills/`,
`patterns/` or `agents/`, and on a shipped script run without `-E`. `from agentic_forge.pr_watch` in prose, which
`pr-watch`'s description has, is not an import, and a description could not have been changed for it. The 3.9 contract
reaches the script too: `dev/hook_smoke.py` imports what it imports and runs it, and `validate_python_compat` now
includes `plugin/bin/`.

**12. The skill path pushes first, and only a fix.** The order is fix, commit, push, then reply, then resolve, as
`run_watch` has it. The skill replied and resolved first, so a failed push left a resolved thread, and the gate read
ready for the unfixed head. `pr-state`'s `push` used to print whatever HEAD was. In live mode it now appears only when
HEAD is on the PR's branch and strictly ahead of the PR's head; otherwise it is null and `no_push` says why, so an
"Everything up-to-date" cannot read as a pushed fix. And it compares `connectors.remote_slug(--repo)` with the PR's
repo, casefolded, as `run_scheduled` does: a PR of another repo gets no `push`, no plan and no trusted thread, since
`git push origin` from such a checkout wrote to the wrong repo's branch of that name. `merge` goes by slug and stays. A
thread whose author is not trusted comes without its `body`, which also ends strangers' large threads filling the report
until the trusted ones are lost to "too large".

**13. Health comes from what was read, and says what was not.** With no `gh` or no alert source, `deploy-status` says so
under `unavailable`: it used to report `healthy` from `"deploys": [], "alerts": {}`. A missing pipeline, or an alert source that is
set and fails, reads `unknown`. With no alert source at all the pipeline's reading stands, because many repos have none and a skill
that can never say healthy tells them nothing; the skill must say the alerts were not read.
The scheduled digest, which reports no provider in its own words, keeps the library's empty sources. `rollout_health`
takes the latest run of each workflow, since a green `Lint` after a failed `Deploy production` read as healthy, and a
cancelled run is `degraded`, not passing. A snapshot's deploys are ordered by `at`, because the first in the file used to
be taken as latest, and more than one without an `at` is refused.

**14. A loop can exit, and a phase can hand off.** `approve` with a red gate is `escalate` at the cap, where it was `revise`
for ever. On `proceed` a phase sets `status: approved` and re-runs `handoff-load` before staging; a `status: draft` that
reached `proceed` was refused by the next phase. `release-summarize` returns `uncategorised`, and with empty `groups` the
skill lists those subjects under Changed, unedited, since a repo with no conventional commits, this one included, had no
way through a changelog that must not be empty or invented. Nothing at all means nothing to release.

## Rejected alternatives

- **`python3 -I -c` or `-P` in each skill.** `-P` is 3.11+, against a 3.9 floor. `-I` drops user site-packages, which is
  where a `pip install --user` PyYAML is. And neither solves the install half.
- **`sys.path.insert` before the import, as `pr-watch` did.** The working directory stays on the path, so a stdlib name
  planted there still runs. Reproduced.
- **Scrubbing `sys.path` inside the script.** The first version did. `sitecustomize` and `encodings` have already run by
  then.
- **A generic `af.py call module.function --json`.** One command, and it would have kept the whole library as the
  surface a repo's text can talk a model into calling, including the merge. It also could not be pinned to what skills use.
- **Run the outward commands in the script.** Shorter for the skill, and it takes the hooks out of the path; see 4.
- **Block `python -c` in the security hook.** It is legitimate in target repos, as ADR 0051 and ADR 0054 record. It may be
  worth a narrow rule for an import of this library; left open.
- **Vendor a small YAML parser.** So that `handoff-load` always works. A second parser for a security-relevant format,
  which would agree with PyYAML until it did not.

## Residual risks

- **The model can still write inline Python on its own, or leave out `-E`.** Nothing stops it. The skills no longer tell
  it to, and they give it something that works, which removes the reason it had. Tier-0 covers what we ship, not what a
  session improvises.
- **A project's settings are equivalent to hooks.** `env` in a repo's `.claude/settings.json` can set `PATH`, so choosing
  which `python3` runs, or `CLAUDE_PLUGIN_ROOT`, so choosing which `af.py`. `-E` does not reach either. Such a file can
  define hooks that run anything, so this adds no power to what the operator accepts by trusting the project, and is not
  something a script can close. `hooks.json` runs its own scripts without `-E` for the same reason. Without that
  acceptance, nothing in a repository sets these.
- **A role still names the library.** `software-engineer` and `qa-engineer` say to detect the stack with `stacks.detect`,
  and the stack packs mention it, in prose with no way to run it. The role bodies were out of scope for this change, so
  `develop` still passes them the resolved pack paths, and `stack-detect` is there for them. A later role change should
  name it.
- **Literal git lines in a skill do not carry the setting.** `git describe` in `release`, `git -C <repo> diff` in
  `develop`. They run where the session runs, and in a repo-shaped subdirectory would read its config. `af.py` covers what
  it starts and prints, not what a skill body writes out.
- **Health does not know a run's branch.** A failing run of a workflow on a feature branch reads as `failing`, a false
  alarm, and a green one could be the latest of a workflow that failed on the main branch. `gh run list` could be
  narrowed by branch, but which branch means production is the repo's to say. The window is also the last 20 runs, so a
  workflow older than that is not seen.
- **Runs and alerts that were read and empty still read as healthy.** `gh` answering no runs, with alerts supplied and
  empty, is `healthy`, as is an empty snapshot: those are answers, not missing sources.
- **`--query` is typed on a command line.** The skill's placeholder asks for letters and digits, which is all recall
  matches on, but a model composes that line.
- **`--end-of-options` needs git 2.24.** `release-commits` fails on anything older, and says so; a tag starting with `-`
  is refused either way. `GIT_CONFIG_COUNT` needs 2.31 and `safe.bareRepository` 2.38, and an older git ignores both, so
  there this protection is absent, silently.
- **`${CLAUDE_PLUGIN_ROOT}` in a file read with `Read`.** Measured on the CLI 2.1.317: it is expanded to the absolute
  path in a skill body, and a real session ran `knowledge`'s calls from a planted repo with nothing planted running. It
  is not set in a shell (ADR 0102). A pattern or reference read with `Read` should hold it literally, as
  `external_review.py`'s lines there already did; that was not measured. So those files say what it means, and an
  unexpanded one fails with `can't open file '/bin/af.py'` rather than doing anything else.
- **A snapshot's fork flag and associations are what it says.** A recorded `isCrossRepository: false` is believed, and
  `push` is printed. It cannot merge, and it is the operator's own file.
- **The last Tier-2 numbers measured the old lines.** Eighteen skill bodies changed. Which of them to re-run is an eval
  decision, and until then their numbers are for the previous text.

## Consequences

- Behaviour change: `vault-validate` exits 1 when it finds problems, where the inline call exited 0 and printed a list.
  It is what a check should do, and it still prints the JSON.
- Behaviour change: the plugin runs on a `python3` with no packages, except for what needs PyYAML or jsonschema, which
  now says so instead of the whole call failing with `ModuleNotFoundError`. What that leaves such a machine able to do is
  in the CHANGELOG.
- Behaviour change: the `knowledge` skill no longer describes writing a note by hand.
- Behaviour change: a new note's title and tags are quoted in its frontmatter. Notes written before still load.
- Behaviour change: `release.commits_since` raises where it returned `[]`. `spine_e2e` is its only other caller, on a real
  repository.
- Behaviour change: frontmatter holding a YAML alias reads as invalid. Nothing in the repository's fixtures uses one.
- Behaviour change: `merge_readiness` is shut for a fork. The scheduled driver already refused one earlier.
- Behaviour change: `review_loop_decision` escalates an `approve` with a red gate at the cap. A `cancelled` run is now a
  status of its own in the library, so the scheduled digest reads it as degraded too, and health is per workflow there
  as well.
- Behaviour change: a note over 2 MB is skipped by `load_vault`, and a tag named `HEAD` counts as no tag.
- Tier-3's `ops-incident` prompts named `ops.InMemoryPipeline` and `ops.classify_incident`, which invited inline Python.
  They now name the commands.
- `tests/test_af.py` runs each command as a real process, on the `python3 -E` a skill would use, from a directory holding
  a planted `agentic_forge/`, `re.py`, `json.py` and `yaml.py`. Contrast tests run the old form, and git without the
  setting, against the same trees and watch them fire. Every call documented in a skill or pattern is parsed, as written,
  by the real argument parser.
- `tests/test_vault.py`, `tests/test_review_loop_shape.py` and `tests/test_pr_watch_merge.py` read the skills' calls, so
  they follow the new form. Where that changed what they assert, the CHANGELOG says how.
