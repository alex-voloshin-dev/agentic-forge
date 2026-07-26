---
type: release
feature: agentic-forge-2026.7.11
status: final
version: 2026.7.11
date: 2026-07-26
changelog:
  - "Fixed: a heredoc body is data, not a command (ADR 0079) — writing a *document about* the environment-dump rule was blocked by that rule, because the classifier scanned the whole command string. Bodies are now stripped before classification unless their receiver executes them (an interpreter on the opening line, or a remote shell), and the block message names the file-write workaround"
  - "Added: `plugin/bin/state_migrate.py` (ADR 0080) — the migration ADR 0072 never shipped. A hand migration into the guessed directory name fails silently in BOTH directions: reads fall back to the legacy in-repo path, so the directory stays alive and the moved history is orphaned. The CLI concatenates rather than moves, de-duplicates, validates every line before removing anything, and leaves the committed `config.json` alone"
  - "Added: `session_start` prints the resolved state root once when a legacy in-repo state directory survives — the slug is a digest of the absolute path, which nobody guesses"
  - "Changed: the audit log is named a BOUNDED ROLLING WINDOW, not durable history (ADR 0080) — the bounds are configurable (`logs.max_bytes`, `logs.keep_bytes`, defaults unchanged) and a rotation now records how many bytes of the oldest records it discarded"
breaking: []
---

# Release 2026.7.11

A same-day follow-up to 2026.7.10, made entirely of what installing 2026.7.10 in the field
revealed.

## The verification worked, and that is the point

The field addendum confirmed both code-level fixes **by behaviour, not by reading**: the
environment-dump rule was precise on all seven documented cases, and the in-repo state directory was
no longer recreated (on 2026.7.9 the same test failed in 16 seconds). Then it found two things a
release can only learn by being installed.

## A guardrail that could not be documented

Writing a **document about** the environment-dump rule with `cat >> report.md <<'EOF'` was blocked
**by that rule** — the classifier scanned the whole command string, and the document quoted the
commands it documents.

The evidence here is unusually direct: reproducing it required a script that **could not itself be
written with a heredoc**, and then the CHANGELOG entry for the fix tripped a *different* rule for
quoting a destructive command as an example. Two rules, two false positives, one session, both on
prose.

The root cause was narrower than it looked and wider than the reported symptom: the rule added in
2026.7.10 was a raw-text scan, skipping the command-word discipline (ADR 0054) that exists exactly
so that quoting something dangerous never blocks. Heredoc bodies are now stripped first — unless the
receiver runs them, which keeps `bash <<EOF`, `ssh host <<EOF` and `cat <<EOF | bash` fully in
scope.

The reporter ranked this a P3 and said plainly they would not trade the block for it. That framing
is why the fix narrows the scope rather than weakening the rule.

## The migration 2026.7.10 forgot to ship

ADR 0072 moved state to `~/.agentic-forge/state/<repo-slug>/`, where the slug is the repo name plus
a digest of its absolute path — **which nobody guesses**. A hand migration into the obvious name
fails silently in **both directions at once**: reads find nothing at the resolved root, fall back to
the legacy in-repo path, and keep using it. The directory stays alive *and* the moved history is
orphaned, with every component behaving exactly as designed and the cleanup looking like it worked.
In the field that was 16,676 records.

Now: `session_start` names the resolved root when a legacy directory survives, and
`plugin/bin/state_migrate.py` performs the migration — **concatenating** rather than moving, because
the old install keeps appending while you migrate (102 records landed after the reporter's copy),
de-duplicating so re-running is safe, and validating every line before removing anything.

## What the audit log actually is

Ten days of one repo's use produced 8.1 MB / 16,780 records. Against a 10 MB bound that is rotation
inside a fortnight — discarding exactly the history a migrating user just took care to preserve.
The reporter named the contradiction precisely.

Archiving the trimmed head would be unbounded growth under another name, which is the defect
rotation exists to fix. So the contract is **stated** instead: a bounded rolling window, not durable
history. Its bounds became configurable, a rotation now records what it discarded, and durable
evidence remains the diagnostics bundle.

## Verification

- **Tier-0**: `validate.py` (0 errors, 0 warnings), `pytest` (coverage 97.9%), `ruff`, `mypy`.
- **New tests**: 18 for heredoc scope, asserted from both sides (documentation passes; an executed
  body stays in scope); 9 for the migration CLI, including records that arrive after a hand copy,
  re-run safety, and abort-on-corrupt-line.
- **Tier-1 / Tier-2 not re-run**: no skill `description` and no skill body changed. The Tier-2
  numbers from 2026.7.10 (`deep-review` 0.950, `software-engineer` 1.000, measured under the shipped
  configuration) still describe this release.

## Not validated

- **A two-step evasion remains possible** — write a script with a heredoc, execute it in a later
  command. True before this change; the documented limit of an accident-guard rather than an
  adversarial sandbox.
- **`state_migrate.py` has not been run against a real legacy repo** other than this one's dry run.
- **Migration is not automatic**, by choice: moving a user's data unasked is the behaviour ADR 0072
  exists to prevent.
- **The PR watcher still has no real-PR run** (a debt since ADR 0045).
- **Surface growth is unaddressed**: fifth shipped CLI, three-deep `PreToolUse` chain, a wider
  config — all added within a week. A consolidation pass is recorded as owed before a sixth.
