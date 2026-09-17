# ADR 0097 — Tier-2 measured the installed plugin, not the tree under test

Status: Accepted (implemented)
Date: 2026-09-17

## Context

`diagnostics-bundle`'s assertion *"the final message reports the absolute output path and the
audit/diagnostics counts"* failed **5 runs out of 5** — twice, before and after a fix aimed
squarely at it. The fix was right: `build_bundle.py` had never printed the counts the skill tells
the operator to report, and ADR 0096 made it print `Records: audit N, diagnostics N`, verified by
hand on this repository. The assertion failed anyway, at the same 5 of 5.

Rather than guess a third time, one session was run by hand and its final message read. The session
had already diagnosed it, in its own words:

> *"Resolved the active plugin (`CLAUDE_PLUGIN_ROOT` was unset) to the **installed version
> agentic-forge 2026.9.3** and ran its `build_bundle.py` …"*
>
> *"The command printed the path and window but **no `Records:` line** — this 2026.9.3 build
> predates the ADR 0096 change the skill notes mention."*

Ten skill bodies invoke their scripts as `${CLAUDE_PLUGIN_ROOT}/skills/<name>/scripts/…`:
`architecture`, `develop`, `diagnostics-bundle`, `engineering-standards`, `marketing`, `plan`,
`pr-watch`, `product`, `research`, `ux-design`. The eval harness sets that variable **nowhere** —
it appears in no line of `agent_eval.py`, `skill_eval.py` or `_eval_cli.py`. A Tier-2 session
therefore resolves it however a live session would: to whatever plugin is installed on the machine.

So for every skill that shells out to its own script, **Tier-2 has been grading the installed
plugin**. On a maintainer's machine that is usually the last release; in CI, where nothing is
installed, the script cannot be found at all. The number was never about the tree under test.

## Decision

1. **The Tier-2 transport points the session at the plugin under test.**
   `agent_eval.claude_cli_runner` takes an `env` mapping, merged over `os.environ` for the
   subprocess; `_eval_cli.build_runners` takes `plugin_dir` and sets
   `CLAUDE_PLUGIN_ROOT=<plugin_dir>` for both the component and the grader. Both CLI wrappers
   already had `plugin_dir` in hand and simply were not passing it.
2. **One construction site keeps it true.** `build_runners` is the single place both Tier-2 CLIs
   build a transport, so the agent path gets the same treatment even though no role reads the
   variable today — a role that starts to will not have to discover this again.
3. **The affected numbers are not retracted, they are re-stated.** Every Tier-2 result for the ten
   script-invoking skills measured a *mixture*: the skill body under test, driving a script from
   the installed plugin. For the run recorded in the CHANGELOG that mixture was `2026.9.3`'s
   scripts against this tree's bodies — a close relative of the truth, not the truth. They are
   re-run on this change; the CHANGELOG entry says which number replaced which.

## Consequences

- This is the seventh instance in four days of a check measuring something adjacent to its claim,
  and the widest: not one assertion or one runner, but a whole tier's relationship to the code it
  grades. It was found the same way as the others — by refusing to accept "5 of 5 failed" as noise,
  and by reading one transcript instead of guessing a third fix.
- The lesson that generalizes: **an eval that runs the product through a path the product resolves
  at runtime must pin that path.** The plugin root here; `$HOME` in ADR 0094 (a Tier-2 run wrote
  into the operator's real `~/Downloads`); the working directory in ADR 0090 (an empty temp dir).
  Three variables, one rule, and the harness now pins all three.
- CI never had a plugin installed, so the script-invoking Tier-2 cases could only ever have failed
  there. That they were never run in CI (Tier-2 is on demand, ADR 0083) is why this survived.
