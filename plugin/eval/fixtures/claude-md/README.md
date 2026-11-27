# CLAUDE.md fixtures for the `omitClaudeMd` A/B

`dev/run_agent_evals.py --claude-md <file>` copies a file from here into every case's workspace as
`CLAUDE.md`, so a role either loads it or omits it (`--omit-claude-md on|off`). The runbook section
"CLAUDE.md in an eval session" in `docs/eval-runbook.md`, and the ADR 0113 amendment, describe how.

## `typical-project.md`

The rules of a plausible Python service ("Ledgerline"): layout, commands, style, types, errors, input
handling, data access, logging and secrets, testing, commits, and review conventions. Its size is
typical for a project CLAUDE.md, so the token gap between the two arms is realistic.

Most of it is general good practice that a review lens applies anyway, so losing it should cost little.
Two rules are project rules that a reviewer **should honour when reviewing**, and each matches an
assertion the lenses already carry. If the lens loses quality without the file, it shows up here:

- **Input from a request:** an index taken from a request is checked explicitly, `0 <= i < len(seq)`,
  because a negative index silently wraps; catching `IndexError` is not validation; reviewers treat an
  unchecked index as major. This matches `reviewer` case 1: the verdict is `changes`, the fix adds
  validation rather than catching `IndexError`, and the review names the negative-index wrap.
- **Logging and secrets:** no secret in a log line at any level; reviewers treat one as major. This
  matches `security-engineer` case 2: the token written to the log is flagged.

The review conventions (verdict words, the severity scale, "a correct rename gets `approve`", "a cache
design states its invalidation") agree with the other cases' assertions. No rule contradicts an
existing assertion, so a lower score in the `off` arm (file loaded) cannot come from the file telling
the lens to do something the contract marks wrong.

A rule that only this file states, and no assertion checks, would be invisible to the A/B. If a run
needs one, add a case for it to the role's contract first.

**In the `on` arm the file is still in the workspace.** The session does not load it, but a lens can
find it with `Glob` and open it with `Read` like any other file. A subagent with `omitClaudeMd` reviewing
a real repository has the same exposure. Before concluding from an `on` arm, check its transcripts for a
read of `CLAUDE.md`; the runbook gives the command. An `on` arm that read the file did not measure its
absence.

The file is about 8,300 characters, roughly 2,100 tokens. Its first heading, `Ledgerline — project rules`,
is what the A/B's probe asks each arm to quote. The `off` arm must quote it and the `on` arm must not, or
the arm is INVALID. Keep a distinctive heading at the top if you edit the file. `--claude-md` refuses a file
without one: the heading must be at least 12 characters and two words, and appear in neither the probe's
question nor `none`. Any edit changes the arms' input fingerprint, so arms run before and after it are never paired.
