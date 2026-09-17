# ADR 0098 — The harness says what it measured

Status: Accepted (implemented)
Date: 2026-09-17

## Context

Seven times in four days a check measured something adjacent to what it claimed (ADRs 0082, 0090,
0094, 0096 ×3, 0097). Each was found by a person refusing to accept a number — "36 of 36 misses",
"5 of 5 failed, twice" — and reading one transcript. The seventh, ADR 0097, is the one to learn
from: Tier-2 had graded the *installed* plugin instead of the tree under test, and the session
had said so in its final message on the very first run. Nobody read it, because nothing showed it,
because the run never said which plugin it ran.

The question that found all seven is the same: *between what this check reads and what it claims
about, what is in the gap?* This ADR puts that question into the instrument, in four places.

## Decision

1. **Every run prints its provenance, and Tier-2 stores it.** `_eval_cli.provenance` reads the
   plugin root and its manifest version, the git commit (`+dirty` when the tree differs from it),
   the model, the `HOME` the session inherits and the interpreter; `provenance_line` prints one
   line at the top of every runner — Tier-1, Tier-1b, both Tier-2 CLIs, Tier-3 — and both Tier-2
   CLIs put the dict on the benchmark under `provenance`, so a recorded history says which tree
   each number came from. ADR 0097 would have read `plugin=~/.claude/plugins/cache/…/2026.9.3` on
   its first run instead of its third.
2. **A Tier-2 FAIL keeps one failing case in its own words.** `_run_passes` records the first case
   that fails an assertion — run, case, the reply's tail (600 chars) — under
   `sessions.failed_sample`, and `gate.tier2_evidence_lines` prints it after the failing
   assertions as `sample (run R case C said): …`. Naming the assertion (ADR 0096) said *what*
   failed; this says *why*, without a paid re-run. It is exactly the transcript that cracked ADR
   0097, kept by default.
3. **The session variables a body may use are a contract the harness pins.**
   `_eval_cli.SESSION_VARS_PINNED` (`CLAUDE_PLUGIN_ROOT`, `CLAUDE_SKILL_DIR`) is what
   `session_env` sets for every Tier-2 and Tier-3 session — to the tree under test, and for a
   skill run to that skill's directory; `SESSION_VARS_INHERITED` is the (currently empty) list of
   variables deliberately left to the real environment, each with its reason. A test scans every
   `${VAR}` in every SKILL.md and agent body and holds it to the union, and a second test holds
   `session_env` to the pinned set, so the sets cannot drift from each other or from the bodies.
   The next variable a skill starts to use will fail Tier-0 until the harness says what it does
   with it.
4. **Tier-3 is pinned too.** Its phase runner built its transport outside `build_runners`, which
   is how it missed ADR 0097's fix the same day: its phases invoke the very skills whose bodies
   call `${CLAUDE_PLUGIN_ROOT}/…`, so the 5/5 recorded in ADR 0096 ran this tree's bodies against
   the installed release's scripts. It now passes `session_env` and prints its provenance; the
   scenarios re-run on this change and the CHANGELOG says what the number became.
5. **A transcript before a second fix.** Written into the runbook as the rule: when a gate fails
   the same assertion N of N twice, the next action is to read one session, not to change code.

## Consequences

- The instrument now answers the audit question on its own: which tree, which home, which
  interpreter (provenance); which assertion (ADR 0096); what the session said (the sample); which
  variables a body may lean on (the contract). A number without those four is the shape every one
  of the seven took.
- The Tier-2 and Tier-3 figures recorded through 2026.9.4 for the ten script-invoking skills are
  re-stated as mixtures (ADR 0097) and re-run here; the ones for skills that invoke no script are
  unaffected.
- `provenance` is best-effort by design: a tree with no manifest or no git yields `?` fields and a
  line, never an exception — the run must not fail because the description of the run could not
  be completed.
