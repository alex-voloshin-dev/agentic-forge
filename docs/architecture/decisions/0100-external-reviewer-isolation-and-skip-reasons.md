# ADR 0100 — External reviewer: opt-in isolation, and skips that say why

Status: Accepted (implemented)
Date: 2026-11-02

Builds on [0042](0042-external-reviewer.md) (the seam) and
[0057](0057-external-reviewer-on-by-default.md) (on by default). Corrects 0042 and 0057 on `command`:
it is no longer repo-configurable at all, and neither are the three settings added here.

> **Amended 2026-11-11 by [ADR 0109](0109-four-field-bugs.md):** `failed` is a third outcome with exit 3 (exit 1 means only `changes`); the prompt goes on stdin, closing the follow-up below; `--skip-git-repo-check` and `--repo` on every call; without `--repo` the git work-tree root, not the cwd, is the repo whose settings are read, which closes the subdirectory limit recorded below for the CLI (the library `review()` still reads `workdir`).

## Context

Three things were true of the seam:

1. `_argv` built `[command, exec, --sandbox, read-only, prompt]`, so the reviewer ran with the
   operator's whole `$CODEX_HOME/config.toml`, and persisted its session files.
2. `run_external` returned `None` for a missing CLI and for any exception, so every failure looked
   the same.
3. `plugin/bin/external_review.py` then printed "produced no parseable review", even after a timeout,
   when nothing had been parsed at all.

A fourth, serious one was found while building this. It affected released versions, and this extension
is on by default.

4. A repo config could set `external_reviewer.command`. Through that it could cause a program it chose
   to run on the operator's machine, and the verdict could be forged, because what the reviewer prints is
   the verdict. A check on the value's shape does not address this. The deciding rule is that **the
   operator chooses the program**.

## Decision

**A structured outcome.** `review_outcome(...)` returns a `ReviewOutcome`: `status` is `reviewed` or
`skipped`, with `review`, `reason` and `detail`.

| Reason | Meaning | CLI exit |
|---|---|---|
| `missing-cli` | The command is not on PATH. | `0` |
| `timeout` | No result before the timeout. | `1` |
| `process-failure` | Non-zero exit, or the call could not be made. | `1` |
| `invalid-output` | It exited 0 and its stdout was not UTF-8, or held no review-shaped JSON, or could not prove an approve: a `changes` beside it did not decode, or more than 1000 openings did not decode. | `1` |
| `isolation-unsupported` | Isolation was asked for and the capability check did not confirm it. | `1` |
| `command-not-configured` | `review()` was passed a `command` other than the configured one. Not run. | Not reachable |
| `disabled` | `review()` was called with `external_reviewer.enabled` false, at either config level. Nothing ran. | Not reachable: the CLI prints its own message and exits `0` |

A skipped outcome has `review=None`, so it holds no verdict and cannot read as approval, and the CLI
writes no `review.md` for it. `run_external()` is unchanged. `review()` returns only the dict or
`None`, and existing call shapes still work, so no skill changed and no eval tier is affected.

`detail` is a tail of at most 500 characters, single-line, with terminal escapes and control characters
removed. They go **before** redaction, because one placed inside a secret would hide it from the patterns
and removing it afterwards would rebuild the secret. It is redacted with `guardrails.redact_secrets`
**before** the 500-character cap, because a cap can cut off a secret's prefix and leave a remainder no
pattern recognises. It is never `str(exc)` for a subprocess error: that string embeds the argv, and the
argv holds the target under review.

**One input cap comes before all of that.** The redaction patterns are quadratic on hostile text:
`"secret" * 20000` took over 25 seconds. So `_safe_line` takes at most 4000 characters of its input, the
start for a finding field and the end for CLI output, which took under 0.1 seconds per field at worst.
Whatever token the cut went through is dropped once the escapes are gone, because the remainder of a
secret matches no pattern. Text with no space in those 4000 characters is dropped whole. A finding field
that was cut ends in `[truncated]`. In the tail of CLI output the cut may also have removed the key or
header that identified a secret, so the first 200 visible characters go as well, and every run of 40 or
more base64-alphabet characters, which is what a PEM body looks like without its header. This is
best-effort: a value in another shape, far enough from its key, can still show.

**Any review-shaped `changes` decides.** `parse_review` used to take the first review-shaped object, and
a reviewer may quote the target, which is attacker-controllable. It now reads every object in the reply:
one review-shaped `changes` anywhere makes the verdict `changes`, whatever its position and however many
approves there are.

- The findings are those of every `changes` object, de-duplicated in reply order. Taking only one would
  let a quoted `changes` with no findings hide the real one's. An approve's findings are not added.
- With no `changes`, the verdict is `approve` with the findings of every approve.
- A `changes` the reviewer only quoted also decides. That costs another look, and an approve that wins
  wrongly costs a missed defect, so this is the side to err on.
- **An approve needs more than an approve.** A `changes` may be the object that failed to decode. So
  when the raw text matches `"verdict"\s*:\s*"changes"` (ignoring case and padding, as the decoded
  comparison does) and no such object is review-shaped, such as a trailing comma, `findings` null or no
  `findings`, the answer is no verdict at all: `invalid-output`. The same text in prose counts too. The
  prompt's own `"approve|changes"` does not match, and neither does a review escaped inside a JSON string.
- The decoder is `JSONDecoder(strict=False)`, so a raw tab or newline in a string does not hide a real
  `changes`.
- `parse_review` no longer uses `agent_eval.json_objects`. Its brace matcher follows quote state across
  the whole reply, so one stray `"` in prose could hide a later object, including the deciding one. Graders
  keep it, since this concern is specific to verdicts.
- Decoding from every opening has no such state, but one failed attempt costs time proportional to its
  position, so doing only that would stall on a brace-heavy reply. So a decoded object is skipped past and walked in
  memory, only `{` followed by `"` counts as an opening, and more than 1000 openings that do not decode
  stop the scan. What was decoded until then still counts: a `changes` decides, and an approve is refused
  with `invalid-output`, since the rest of the reply was not read. So padding after a real
  `changes` cannot erase it, and padding cannot help an approve. Over 1000 bad openings BEFORE the verdict
  gives `invalid-output`, so a reviewer that echoed them turns the review into a skip, never an approve.
- Stdout that is not UTF-8 is `invalid-output`, not `process-failure`: the reviewer ran and answered. Only
  stdout counts. A bad byte in stderr neither spoils a good reply nor hides a non-zero exit.

**Finding fields get the same treatment as `detail`.** `severity`, `location`, `issue` and `suggestion`
all go through `_safe_line`: capped at 4000 characters of input as above, terminal escape sequences
removed whole, control characters removed, secrets redacted, one line. They reach the terminal,
`review.md` and the session.

**The CLI refuses a symlink for `--target` and `--out`,** with a message and exit `1`, before anything
runs. A link at `--target` could send a file the operator did not mean to the third party, and a link at
`--out` could overwrite one. A dangling link counts. The write itself also uses `O_NOFOLLOW` where the
platform has it, because the review can run for minutes after the check. A failed write is reported with
exit `1`. The target is read with `O_NOFOLLOW` too and checked with `fstat` for a regular file, so
nothing can be swapped in between the check and the read, and a target that cannot be read, or is not
UTF-8, gets a message and exit `1`.

**A symlinked parent directory below the repo root is refused the same way.** `docs/link/plan.md` could
send a file from outside the repo, or write outside it, and the repo is what may be under review. The path
is walked one component at a time as the OS does, so `link/..` does not hide a link, and `--repo` is
resolved first. A link above the resolved root stays allowed, because `/tmp` and home directories are often
links, and a target or `--out` outside the repo stays allowed, because that path is the operator's own.
`--out`'s parents are checked again just before the write.

**Opt-in isolation.** Three new settings under `external_reviewer`: `isolated` (default `false`),
`model` and `effort` (default `null`).

- `isolated` adds `--ignore-user-config --ephemeral`.
- Ignoring the user config also drops the operator's model and effort, so `model` is passed as
  `--model` and `effort` as `-c model_reasoning_effort="<value>"`. Each is passed only when set, with
  or without isolation.
- Before each isolated run, `<command> exec --help` runs through an injectable seam (`HelpProbe`) with
  a 15-second timeout. Both flags must appear as whole flags. Otherwise the review is skipped with
  `isolation-unsupported`.
- Both subprocess calls run with `stdin=subprocess.DEVNULL`, isolated or not. The help text says piped
  stdin is appended to the prompt, so the caller's stdin must not reach the reviewer.

**`review()` reads the settings.** `review()` goes through `configured_review_outcome`, which resolves
the settings for `workdir`. Skills call `review(diff, kind, command=<cfg>)` and pass nothing else, so
without this `isolated: true` would be honoured by the CLI and silently ignored by all seven auto-wired
workflows, which is where the reviewer actually runs. The default is off, so calls without the setting
behave as before. `run_external` stays the plain primitive: it reads no settings and is never isolated.

**`review()` honours the opt-out.** With `enabled` false at either config level,
`configured_review_outcome` returns a `disabled` skip before anything else: no capability check, no
reviewer call and no `command` comparison. The skills check `enabled` before calling, as they always
have. This holds for a session that did not. `review_outcome`, which the CLI calls, does not read
`enabled`, because `--force` is the operator's own override.

**Four settings are the operator's.** `command`, `isolated`, `model` and `effort` are honoured only from
the built-in default or the user-level file. A repo file's values for all four are removed from its
data **before** the merge, so neither the merge order nor any later reader can see them. A value that
differs from what is in effect gets a warning that names the key and does not repeat the value. A value
equal to it changes nothing and gets no warning, because the shipped example carries all four. "In
effect" is what `resolve` will use, not the user file's raw value: an invalid user-level `command`
falls back to `codex`, so a repo's `codex` is no change. The
fallback for a malformed repo file keeps all four from the user-level file, so a repo cannot reset them
by breaking its own file. The schema still allows the keys, because the same schema validates both
files, and rejecting them would drop the whole repo file. The decision belongs to `resolve`.

**A repo config cannot undo a user-level `enabled: false`.** It is an opt-out, and when the reviewer
runs, content goes to a third party. A repo's `true` is removed before the merge with a warning, and
the fallback holds the opt-out too. Without a user-level opt-out a repo may turn the reviewer on. The
operator's own `--force` still overrides both.

**A repo's own `enabled: false` holds when its file is broken.** A typo must not turn a repo's opt-out
back on and send a secret-bearing repo to a third party. So when a repo file is dropped, by a schema
error, a JSON typo, a non-mapping section or its size, whatever can be parsed is checked: the raw text
for `"external_reviewer": {... "enabled": false ...}`, leniently, then the decoded JSON if there is any.
A clear `false` is kept and nothing else in the file is. The malformed fallback holds it too. A false
match only turns the reviewer off, which a repo may do anyway. **The opt-out cannot be known where the
file cannot be decoded at all,** such as one in another encoding, or where it cannot be read, or where
the statement lies past the first 1 MB of an oversized file. The reviewer then stays on, with the
dropped-file warning. So a repo's opt-out needs a file that can be read, and this is not a guarantee beyond that.

**A repo turning off a user-level `true` is allowed, and reported.** A branch can add `enabled: false` to
its own config, and the CLI then exits `0` with no review. It keeps the right, because the opt-out is
what a secret-bearing repo needs and a warning costs nothing. `resolve` warns, naming the override, and
the `disabled` skip's detail and the CLI's message both say the repo's config did it
(`Settings.external_reviewer_disabled_by_repo`). This is only for an explicit user-level `true`: a repo
that opts out while the operator has set nothing is the documented use, and warning about it in every
session would teach people to ignore the line. So a branch can still do this quietly where the operator
relies on the default.

## Why opt-in

The extension is on by default wherever codex is installed (ADR 0057). Isolation on by default would
change the model of everyone who configured one, drop whatever else their config sets, and turn every
older CLI's review into a skip. Those are choices for the operator to make.

## Why a repo file cannot choose `command`

The question is who chooses the executable, not which name it has: a program a repo picks runs with the
operator's privileges, and its output is the verdict.

- The bare-name check stays for the user-level value. It catches a mistake, and an operator who wants a
  path has `--command`.
- `review()`, which the skills call, refuses any `command` other than the one `settings.resolve` gives,
  with `command-not-configured`, and runs nothing. Without this, a session that read the raw repo file
  and passed its value would reopen the hole, and `settings` could not prevent it. Its `command` default
  changed from a literal `"codex"` to `None`, meaning the configured reviewer, so a call without the
  argument still works when the user-level `command` differs. The refusal is an exact string match, so
  a path to the configured program is refused too.
- `plugin/bin/external_review.py` calls `review_outcome` directly, which runs what it is given. That is
  the seam for `--command`.

**Rejected: an allowlist of reviewer names.** It still lets a repo choose. A name says nothing about the
program that PATH resolves it to, and every new reviewer CLI would need a code change, against 0042's
extensibility goal. A denylist is worse, since it has to anticipate every program. Taking the choice away
from the repo needs no list.

## Why a repo file cannot set `isolated`, `model` or `effort`

The repo is what gets reviewed, so it should not configure its own reviewer.

- **`isolated`.** An earlier version of this ADR let a repo turn isolation on, on the reading that it
  could only tighten things. It does not only tighten. `--ignore-user-config` drops the operator's whole
  `$CODEX_HOME/config.toml`, including any provider or hardening settings, so a repo's `true` would
  discard choices the operator made for their own machine.
- **`model` and `effort`.** The value pattern stops a flag or a broken TOML string, not a choice. A repo
  could pick a weaker model or a lower effort, which makes its own review easier to pass, or a costlier
  one on the operator's account.

This also removes a rule. Isolation no longer needs a floor that a repo cannot lower, and a dropped repo
file can no longer take an `isolated: true` with it, because nothing in that file could have set it.

Rejected: letting a repo tighten but not loosen. For `isolated` there is no such direction, as above,
and there is no ordering of model names to compare.

A team that wants one reviewer configuration asks each operator to set it at user level.

## Why no free-form args

The config file can be repo-controlled. An args setting would let a committed file add
`--dangerously-bypass-approvals-and-sandbox`, `--sandbox danger-full-access` or `--add-dir` to a
reviewer running over attacker-controllable text. Every flag is fixed in `_argv` instead, and the
schema's `additionalProperties: false` rejects anything else.

## Why config shapes are checked in code, not by a schema pattern

`model`, `effort` and `command` are the config values that reach argv. They now come only from the
user-level file, where a bad one is a mistake rather than an attack, but it would still reach argv.
`jsonschema` may be absent at runtime, so the schema cannot be the check.

The schema also must not carry a `pattern` for them, even as a second layer. A schema failure drops
the whole file, so a pattern would let one bad `model` switch off `isolated: true` from the same file
and run the review without it. The schema keeps only the types. A repo's value is removed before any of
this looks at it.

- `model` and `effort` must fully match `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`, in `settings` and again
  in `_argv`, whoever built the options. `fullmatch` matters, since `$` also accepts a trailing newline.
  An invalid value is treated as unset with a warning.
- A user-level `command` must fully match `[A-Za-z0-9][A-Za-z0-9_-]*`, the pattern the schema used to
  hold: no path separator and no leading dash. An invalid value falls back to `codex` with a warning.
- Each warning names the key without echoing the value, because that line reaches the session.
- A dropped file's warning holds to the same rule. A schema failure reports the JSON path and the
  validator's name, not the validator's message, which quotes the value. A key the schema does not
  declare is `*`, since the name is the file's text too, and an unknown top-level key is reported only
  at `$`. The operator loses the offending name, and a repo loses a channel into the session.
- That warning says what still applies, and it depends on the path. For a repo file: the user-level
  config, and a clear `enabled: false` from the file. For a user-level file: the repo config and the
  built-in defaults, and it says its `enabled: false` is gone. For the malformed fallback: built-in
  defaults, except the user-level `external_reviewer` settings and an `enabled: false` from either file.
- A file never makes `resolve` raise. Bytes that are not UTF-8, JSON nested too deeply and an integer past
  Python's digit limit each drop the file with the same warning, as does a path that cannot be checked.
  So does a file over 1 MB, unread. So does any failure inside schema validation, reported by the
  error's name only: about 1.4 KB of nested lists under `uniqueItems` raised `RecursionError` there. A
  home directory that cannot be found is reported and the repo file still applies. A merge that
  overflows, or a stderr that is closed, cannot raise either.

**`--command` on `plugin/bin/external_review.py` is not validated, and may name a path.** It is the
operator's own argument on their own command line, not something a repo can set, and pointing it at a
local build is a legitimate use. A test pins this. A value holding a path separator is made absolute
against the caller's cwd before any use. The capability check runs from the cwd and the review from the
repo, so otherwise a relative path could name two different programs, and the operator would not be the
one choosing the second.

## Why no fallback to a non-isolated run

The operator asked for a property. Running without it would do what they ruled out, and it would look
like success. A skip is visible and costs one review lens. So a check that fails, times out or finds
one flag of two is treated as "cannot", without positive evidence there is no run.

## Why not `--ignore-rules`

Its help text reads "Do not load user or project execpolicy `.rules` files". That removes
restrictions, which is the opposite of the goal. A test pins that it is never passed.

## What this does not claim

This is not a sandbox claim beyond what the flags do. From `codex exec --help` (codex-cli 0.164.0):

- `--ignore-user-config`: "Do not load `$CODEX_HOME/config.toml`; auth still uses `CODEX_HOME`".
- `--ephemeral`: "Run without persisting session files to disk".

So isolation does not hide the repo or the disk from the reviewer beyond what `--sandbox read-only`
already does, says nothing about network access, and does not reduce what is sent to the third party.
ADR 0042's trust boundary stands unchanged: findings stay advisory and prompt-injectable, and
`enabled: false` is still the answer for a secret-bearing repo.

**Project-level configuration, as measured on codex-cli 0.164.0.** The help text covers only the user
config, so this was run:

- Not isolated, with `cwd` at the repo and the project marked trusted in the operator's codex config,
  project-level configuration could run a program it named. It did so in a linked worktree of a trusted
  repo as well.
- In an untrusted project it did not.
- With `isolated` it did not, in any case.
- `AGENTS.md` from the repo reached the reviewer in every mode.

So we recommend `isolated: true` for any repo that takes outside contributions, and do not make it the
default, for the reasons under "Why opt-in". It does not stop `AGENTS.md`, so the findings stay advisory
either way. This is one version of a third-party CLI, measured by hand. No test here covers it, and it may
change.

The flags were read from the help text of that one version, and the tests use a fake subprocess or stub
reviewers. One real run of codex-cli 0.164 with `isolated: true` over a large diff returned a parseable
verdict, so that version accepts both flags. Nothing is known about other versions.
`model_reasoning_effort` is not in the help text. It was only confirmed to appear as a string in the
0.164.0 binary, so whether codex honours `effort` remains unverified.

## Follow-ups

Known, and not fixed here:

- ~~**Skills that call the lib inline could be shadowed by repo files on `sys.path`.**~~ Fixed by
  [ADR 0104](0104-skills-run-a-script-not-inline-python.md) (2026-11-03), with the SKILL.md edits. Which evals to
  re-run is recorded there.
- **Pass the prompt on stdin.** That would remove the argv size limit, and the way a NUL byte in the target
  turns a review into a `process-failure` skip.
- **`review()` from a subdirectory** does not see the repo's config, as the known limit below says.
- **A cap on the whole reply,** which is what would actually bound the time to parse one.

## Consequences

- An operator can tell a timeout from an auth failure from a reviewer that ignored the format.
- A skill still sees only `None`. Passing the reason through to the skills would need a SKILL.md change
  and an eval run, and is not part of this decision.
- Known limits, each deliberately left as is:
  - **A broken user-level file loses most of what it set.** With `jsonschema` installed, a `model` that is
    not a string or null, or any other schema error such as `review.passes: 0`, drops the user-level file
    with `command`, `isolated`, `model` and `effort`. Its clear `enabled: false` is kept, as a repo's is, so
    a typo cannot send content to a third party against an opt-out. `isolated: true` is not kept: the
    review then runs non-isolated, and the session is told. A dropped repo file costs nothing here,
    because it could not set those four.
  - **Validation can still be slow, well under the size limit.** `uniqueItems` compares unorderable items
    pairwise, so a `pr_watcher.repos` of many distinct objects is quadratic: 8000 of them, about 100 KB,
    took 64 seconds in one local run. This predates ADR 0100. Nothing fails, so nothing drops the file,
    and it needs `jsonschema` to be installed where the hook runs. A repo file can do this to its own
    sessions, and that includes delaying every hook which resolves settings past its own timeout, the
    security hook among them when it records a block. Fixing it would mean validating without that rule or
    lowering the limit: a follow-up.
  - **`review_outcome`, `--command` and `--force` do what they are told.** They speak for the operator. A
    session that called them directly would bypass the `review()` checks, and this code cannot tell it
    apart from the operator.
  - **A repo-level `enabled: false` is read from `workdir`.** A call from a subdirectory does not see the
    repo's `.agentic-forge/config.json`, the same as the CLI's `--repo` pointed at a subdirectory. The
    user-level settings apply wherever the call is made.
  - **A parent directory can still become a link after its check.** `O_NOFOLLOW` covers only the last
    component. The gap is short for `--target`, whose read comes straight after the check, and short for
    `--out`, which is checked again before the write. Closing it would mean opening each component in
    turn, for a repo already being changed while the CLI runs.
  - **A hostile reply can still be slow to parse, and nothing bounds the total.** The limit bounds the
    attempts at 1000, each at most one pass over the reply, and the input cap bounds each field, but the
    reply's size is not capped, so the time grows with it, and the review timeout has ended by the time
    parsing starts. One local run, on one machine: a 2 MB reply built to fail late on every attempt took
    62 seconds, and a 2 MB reply of 500 worst-case finding fields took 43. A reviewer that wanted to stall
    could already use the whole review timeout, so this was left as is, and a cap on the reply is a
    follow-up.
  - **Isolated runs add one short subprocess**, the capability check.
