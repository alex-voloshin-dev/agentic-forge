# ADR 0102 — A checkout does not choose where state goes

Status: Accepted (implemented)
Date: 2026-11-03

Amends [0072](0072-shipped-cli-and-user-level-state.md) §3: `state.in_repo` is user-level only. Applies
the rule of [0100](0100-external-reviewer-isolation-and-skip-reasons.md) to a second setting.

## Context

ADR 0072 moved generated state to the user level and kept `state.in_repo` as an opt-in, readable from
either config file. A repo's own file could therefore turn it on. The state root is then a directory the
repo controls, and git commits symlinks, so the names the plugin's writers open could be links the repo
chose. Those writers used `write_text` and `open("a")`, which follow links, and they run from hooks without
anyone asking. The result was that opening an untrusted repo could cause a write to a file outside it, with
the permissions of the user. It was reproduced on master.

Every part of that was working as designed, which is why a check at any one place would not have been
enough.

## Decision

**1. `state.in_repo` is the operator's.** `_drop_repo_section` removes the repo file's whole `state`
section before the merge, the way `_drop_repo_reviewer_settings` removes the reviewer's keys, so no later
path can read it. The malformed-config fallback restores the user-level value, so a malformed repo file can
neither turn it on nor reset it. A value that differs from the one in effect gets a warning naming the key
and not the value; one that equals it gets none, because the shipped example has `in_repo: false`. There is
no env override, and none is added.

**2. A state write never follows a symlink, wherever state is.** An operator who chose `in_repo: true` still
opens hostile repos, so the first decision does not protect them. `state_io` is the one way to write state:

- A full write is a temp file in the same directory, opened `O_EXCL | O_NOFOLLOW`, and then `os.replace`,
  which replaces a name and does not write through it.
- An append opens `O_APPEND | O_CREAT | O_NOFOLLOW | O_NONBLOCK` and takes regular files only.
- Both first refuse a symlink below an **anchor**, before any `mkdir`, since that would itself write at the
  target. They also refuse the wrong type at the name or a parent. In a repo the anchor is the repo root, so
  a linked `.agentic-forge` is refused. At user level the anchor is the state directory itself: a checkout
  cannot plant anything at or above `<slug>`, so a check there would only lose the logs of an operator who
  relocated one repo's state with a link. `archive/` is exempt at user level for the same reason.
  `~/.agentic-forge`, home directories and `/tmp` are often links too.
- The temp file is created `0600` and given its final mode before any content is written. Its name has a fixed
  length, so a name that fits is not refused for the temp file's sake. A full write therefore needs the
  directory to be writable, even if the file is; a plain write needed only the file.

The walk is what makes a refusal a policy, and the syscalls are what hold if a link appears after the walk.
A test blinds the walk to show that.

A refusal is `StateWriteRefused`, an `OSError`. Hooks treat it as a record not kept. They do not report a
crash, because a hook that announced one on each call would hand a repo a way to spam the session. That covers
everything a checkout's shape can cause, including a directory at a log's name and a file at the state
directory's. A hook crash must not be silent, so a crash notice whose once-per-session marker cannot be saved
still shows, and repeats: at user level, an unwritable state root is the operator's own broken environment, and
a checkout cannot cause it. The one exception is `state.in_repo`, where a checkout controls the path and could
put a line on every tool call. Only there is the notice dropped, by `once_per_session(..., if_unsaved=False)`.
Any other `OSError` keeps today's handling. Three refusals are not quiet, on purpose:

- The scheduled queue drain lets it fail its job: it is not a hook, and an unsaved tick means the same PRs are
  watched again.
- `run_scheduled` exits non-zero and says so if it cannot save job state. No cursor advanced, so every job would
  run again on the next poll, whatever its cadence, and exiting 0 hid that.
- A rotation whose archive is refused returns with the log untrimmed. Trimming anyway would let a link at
  `archive/` delete records. It records an anomaly in the diagnostics log, once per rotation and so at each
  session start, because the log is now growing past its bound. Only state in the repo reaches this through a
  link: at user level `archive/` is exempt, so an operator's link there keeps working as it did before this ADR.
  A disk that cannot take the archive still trims, and the record now says that the archive failed, rather than
  blaming `logs.archives`.

**3. Readers do not read through a link either.** `existing_state_file` returns only a regular file reached
without a link, and `os.devnull` when the only candidate crosses one, so all five callers see "no state yet"
without changing. This is what keeps another file's content out of a digest and out of a diagnostics bundle,
which exists to be shared. Rotation skips a linked log, since archiving it would copy the target into the
state directory.

**The migration and its notice.** `state_migrate` checks each target before reading or comparing it. A link
there used to be merged through, and the legacy file then deleted, while every reader refused the link: the
state was gone. It now skips that file, names it, keeps the source and exits `1`. It deletes a legacy
`notices.json`. The session-start notice lists only the names the migration handles, so following it ends it.
It gives a real path and a dry run, and says to add `--apply`, because `${CLAUDE_PLUGIN_ROOT}` is not normally
set in a shell. No filename read from the directory appears in the notice or in the migration's output: a repo
chooses those, the notice reaches the model, and the migration may be run by one.

**4. The vault directory must resolve inside the repo.** `docs/knowledge/` is on a repo path and is reachable on
a default install. A committed link there could put notes in a directory of the repo's choosing, where a new `.md`
file can have a meaning of its own, and could bring titles from outside into the session context, on a plain clone,
with no skill involved. The rule is a path comparison: `os.path.realpath(vault)` is the repo or below it. So a link
at any level, through any chain, is judged by where it ends, and a link staying inside the repo works (a committed
`docs -> website/docs`). It starts no process, so the session-start hook gains none.

The repo is the nearest ancestor of the working directory holding a `.git` entry, or the working directory if there
is none. A session often starts in a package inside the checkout, and measuring from there refused a package's
`docs -> ../../docs` and silently took the map out of the session. It is found by walking up, and deliberately not
with `main_repo_root`, which follows a `.git` file's pointer to wherever that says. So a linked worktree is its own
repo, and one whose `docs` links to the main checkout needs the setting.

Outside the repo, a write raises `StateWriteRefused`, naming the path and the remedy, and creates nothing. Unlike a
log line, a note is what the user asked for and is watching, so a skill has to be able to say it was not saved; a
traceback from the `python -c` a skill runs is how vault errors surface today. A read acts as an empty vault, with
no crash, so nothing reaches the session context. So that a vault kept elsewhere does not vanish silently on upgrade,
the session-start hook prints one once-per-session line saying it is not read and naming the setting, in constant
text. `validate_vault` reports it as its one problem.

An operator who does keep a vault elsewhere sets `knowledge.allow_external_vault`. It is user-level only, dropped
from a repo file before the merge and restored in the malformed-config fallback as `state.in_repo` is, and it wants
a real `true`, because on is the dangerous side. It applies to every repo, so it also admits a link the operator did
not make; that is the price of an operator choosing it.

Inside the vault, writes go through `state_io` with the vault directory as anchor, so a leaf link or the wrong type
is refused, with or without the setting. `add_note` checks what it will write before anything, including `scaffold`,
so a refused name leaves nothing behind on a fresh vault. It and `scaffold` check only what they will write: an
existing `README.md` is never written, and a map-of-content already holding the link is not changed, so neither
stops a capture. A read-only file that would change is refused, because a replace needs only the directory and would
overwrite it without a word. A linked file and a note that is not UTF-8 are skipped when reading.

The session-start hook now builds its context separately from its notices, since a failure there used to discard
notices whose once-per-session marker had just been spent: one bad file could hide a warning about the repo that
holds it. What it reports of a crash is the exception's type, since the text can repeat a repo's file. For the same
reason `frontmatter.parse` turns anything PyYAML raises into a `FrontmatterError` that does not repeat it, and
`load_vault` takes a `title`, `type` or tag only if it is a string, before any `str()`, so an alias bomb or a huge
int costs that note and not the session.

### Rejected for the vault

**Asking git whether the link is tracked.** This lived on the branch for one commit, so that an operator's own link kept
working with no setting, and a re-review broke it three ways. In a submodule the outer index holds only the gitlink,
so a link tracked inside it reads as untracked. Under a case variant on a case-insensitive filesystem, git is asked
about one spelling and the filesystem answers for another. And a bare-repo-shaped subdirectory answers git's
discovery when the repo is `.`, so the question goes to a repository the checkout made. It ran on writes only, too,
so the session context was still exposed, and adding a process to session start was not acceptable. This is the same
shape as a command parser: each fix answers the last bypass, about a tool whose answers depend on the checkout.

**Refusing every link, with no exception for one inside the repo.** A link that stays inside chooses nothing the repo
could not already do with a plain directory, and refusing it would break working layouts for no gain.

## The rejected alternative: keep the repo-level setting, add no-follow only

It would have closed the write and kept the setting working for the repos that use it. It was rejected:

- A checkout would still choose where the plugin writes, including writing generated files into a repo whose
  owner never asked for that, which is what ADR 0072 set out to stop.
- The repo would still control the contents of state it could then read back: job history, a queue, and
  notices that decide whether the operator is told something.
- No-follow would be the only layer. Decision 1 means an ordinary user needs no correct behaviour from any
  writer at all, including one added next year.

The cost is that a repo which wants its state in the tree can no longer say so for everyone who clones it.
Each operator has to choose it, and the choice applies to all their repos.

## Residual risks

- **A race on a directory.** The walk and the open are separate steps, so a process that swaps a directory
  for a link between them is not stopped by the walk. `O_NOFOLLOW` protects the last component only. Such a
  process already runs as the user, or can write to the checkout at that moment.
- **Hard links.** `O_NOFOLLOW` does not see them, so an append to a name hard-linked to another file writes
  to that file. Git cannot commit a hard link, so this needs another delivery route, such as an archive. A
  full write is not affected. A check on the link count was left out: it would also silently stop the logs
  on any backup scheme that hard-links unchanged files.
- **A refused write is silent.** There is nowhere safe to record it, so a repo with a link at a log name
  under `in_repo: true` has no log, and only the absent records show it. A hook crash under such a state root
  gets no notice either.
- **A refused archive means no trim.** Under `in_repo: true`, a link at `archive/` keeps that log growing, and the
  anomaly that says so goes to the diagnostics log, which can be refused by the same repo.
- **Repo-chosen vault text reaches the session.** A note's filename and frontmatter title go into
  `additionalContext` by design (ADR 0018), inside the repo as well, and a repo chooses both.
- **`knowledge.allow_external_vault` is one switch for every repo.** With it on, a checkout's link to anywhere is
  admitted as the operator's own is.
- **The vault rule is checked, then acted on.** The same race as the state walk, and for a link inside the repo that
  moves between the two, the same answer.
- **The nearest `.git` entry decides.** An unpacked archive with no `.git`, under a directory that has one such as
  a home kept in git, measures from that directory, so a link staying inside it is admitted.
- **The skills' `python -c` resolves modules from the current directory first.** So a checkout can shadow a module
  there, and a plugin-only install may not find the module at all. A following release replaces it with a shipped
  script.
- **`pr_watcher` settings stay repo-settable.** A following release handles them.
- **A state home inside a checkout.** An `AGENTIC_FORGE_STATE_HOME` that is relative, or points into a repo,
  puts the levels the walk exempts under that repo's control. The variable is the operator's to set.
- **The budget counter lives in the shared temp directory.** A link planted at its name makes each call count
  as the first, so the cap does not fire for that session. The hook already fails open by design.
- **Windows has no `O_NOFOLLOW`.** The walk is then the only guard.

Found while reviewing this, older than it, and left for a later release:

- `_merge_jsonl` appends old records after new ones, so a merged log is not in time order.
- `main_repo_root` does not verify a `gitdir:` pointer against the back-pointer in the worktree's git directory,
  so a `.git` file, which git itself will not deliver, can key state to another checkout.
- Committed regular `pr-watch-queue.json` and `schedule-state.json` at the legacy location stay authoritative
  until a state file exists, and the migration promotes them.
- A repo can erase its own audit trail with repo-level `logs.*` bounds.
- Archive files get the umask's default mode rather than the log's, and state directories are not made private.

## Consequences

- Behaviour change: a repo-level `state.in_repo` is ignored. Such a repo's new state goes to the user-level
  root. Its existing files stay readable by the legacy fallback until a new file appears beside them, and the
  session-start notice names the `state_migrate` command.
- `add_note` can now raise `StateWriteRefused`. The skills that call it state no handling for it, so the
  traceback is what the user sees.
- `tests/test_state_writes.py` holds the regression, run through the real hook with and without `jsonschema`,
  and an `ast` scan of `plugin/lib`, `plugin/hooks/scripts` and `plugin/bin` that fails on any write around
  `state_io` outside a short allowlist.
- `plugin/bin/external_review.py` already refuses links for `--target` and `--out`.
