# ADR 0094 — The audit: the same three shapes, everywhere else

Status: Accepted (implemented)
Date: 2026-09-13

## Context

ADRs 0081–0093 fixed thirteen defects, one at a time, each found by reading a field bundle or a
miss. Read together they are three shapes, not thirteen defects:

1. **A verdict from nothing.** A session that never ran, a timed-out subprocess, an errored `gh`
   call, an empty list — scored as a miss, a failure, "healthy", or a pass.
2. **A message to nobody.** A hook printing its only warning to stderr and exiting 0 (Claude Code
   discards it); a crash recorded only when an opt-in is on; a stale comment above a live gate.
3. **A stand that presupposes what it does not carry.** A prompt about "this incident" with no
   incident, a contract asserting "no test is weakened" over `files: []`, a role told to "load" a
   skill it cannot invoke.

So the whole plugin was swept for those shapes — fifteen classes, six areas (hooks and guardrails,
the eval harness, eval content and fixtures, CI and docs, the runtime CLIs, skill and agent
content), each area read by an auditor with the class list, every candidate traced through its
call path, the guardrail ones executed against the live classifier, plus deterministic sweeps
(3.9 AST parse over the hook closure, `subprocess` calls without `timeout`, empty-verdict sites,
placeholder and referent scans over every trigger prompt). About fifty findings survived
verification; nine were high. The fix was done as one change set, by area, and this ADR records
what was decided rather than every line (the CHANGELOG has those).

## What was found, by shape

**A verdict from nothing.** The PR watcher scored a `claude -p` reply that never ran (a usage
limit, an auth error) as *rejected* and posted a canned answer publicly on the reviewer's thread.
The eval runner met the same envelope with three full retries, then dropped the whole role with
every finished session ungraded — and a `--max-turns` cap hit, being deterministic, was retried
three times at full cost. The grader parser took the first JSON object of any shape, so a stray
object scored a case 0/N silently. Tier-1 failed a whole skill when three of a prompt's five
calls were invalid — the per-item floor ADR 0093 had just replaced for Tier-1b; it had fired on
ADR 0084's run. A failed `gh run list` degraded to `[]`, and `rollout_health([], [])` printed
"healthy". `rm -rf /home/runner/work/repo/dist` was blocked as a system directory on every Linux
CI runner, and `chmod -R u+x` counted as permissive; `git push` inside a heredoc or a `grep`
argument ran the 110-second commit gate — and blocked the command when `validate.py` was red.

**A message to nobody.** The merge-preflight warning (ADR 0076) and the subagent soft-cap warning
went to stderr with exit 0 — reaching nobody, for months. The PR-created reminder (ADR 0063) was
bare stdout from a PostToolUse hook, which is shown in transcript mode only. Every hook's crash
was "recorded" through a diagnostics channel that is off by default, so a dead guardrail on a
default install looked exactly like a healthy one. A malformed config was dropped whole with a
stderr line from every hook on every tool call. `AGENTIC_FORGE_SKIP_TEST_GATE=0` skipped the gate.

**A stand that presupposes.** `engineering-standards` and the nine `*-patterns` packs are
`disable-model-invocation: true` — absent from the listing, uninvocable by name — while `develop`,
`software-engineer` and `qa-engineer` were told to "load" them by name with no path: the standards
the plugin advertises were not reachable by the roles meant to apply them. `research` routed web
work to a `deep-research` skill that does not ship and carried no `WebSearch`; `marketing` forked
a `research` *role* that is a skill. `architecture`, `plan` and `product` refused to work without a
handoff artifact and had no branch for its absence — the ADR 0091 stall. The `diagnostics-bundle`
Tier-2 cases isolated the working directory but not `HOME`: a run wrote real zips into the
operator's `~/Downloads` and packed their real `~/.claude` transcripts into graded output, by
contract. The ten knowledge packs' Tier-2 cases asserted "no existing test is weakened" over
`files: []`; `skill-factory`'s asserted files under `plugin/` on a stand with no `plugin/`.
Three of `incident-response`'s four Tier-1b prompts carried no incident; `knowledge`'s asked for
notes with no vault seeded. Two `X` placeholders were still in `should_not_trigger` lists.

## Decision

1. **Python 3.9 stays the floor for hook-reachable code, and CI tests it.** Hooks run under the
   user's bare `python3` — a stock macOS gives CPython 3.9.6, and that is what the field bundles
   ran — while the repo's tooling requires 3.11. Moving the hooks to "the latest" would make them
   fail to parse on a stock Mac, and a hook that fails to start fails *open* and silent. The floor
   costs a handful of idioms (`from __future__ import annotations`, no `match`, no `zip(strict=)`,
   no `datetime.UTC`) on ten lib modules; it was assumed, not tested. `ci.yml` now runs
   `dev/hook_smoke.py` under 3.9 with nothing installed: every shipped file compiles, every
   hook-reachable module imports, every hook runs on a minimal payload and prints nothing or JSON;
   a hook without a smoke payload fails the test. `mypy` now covers `plugin/bin` too.
2. **A hook speaks through one channel.** A non-blocking warning is `diagnostics.hook_notice`
   JSON on stdout — `systemMessage` for the operator, `hookSpecificOutput.additionalContext` for
   the model — never stderr. A hook crash is `diagnostics.hook_crash`: recorded regardless of the
   opt-in (the one exception to it, like outward actions) and announced once per session. A
   dropped config rides on `Settings.warnings` and is announced once at SessionStart.
   `diagnostics.jsonl` is rotated like the audit log. Merge-preflight's git reads share one
   12-second budget under the hook's 15. `AGENTIC_FORGE_SKIP_TEST_GATE` is a boolean.
3. **A session that never ran is undetermined, everywhere a `claude -p` reply is consumed.**
   ADR 0093's shape, generalised: `agent_eval.session_outcome` reads the envelope (`is_error`, a
   non-success subtype, `error_max_turns`, zero turns) and the runner raises
   `SessionUndetermined` / `TurnCapHit` / `SessionTimedOut` at once — no retry for an answer, one
   retry with a `T` for a timeout, backoff only for a transport failure. Tier-2 records the case
   as unmeasured and fails the component above `gate.MAX_UNDETERMINED` (0.10); Tier-1 records an
   `INVALID` call with the reason and gates on the pooled share of calls that never ran — the
   router's own non-answers stay ADR 0064's reported discard; capping those too failed
   `deep-review` at 7/55 with recall 1.000 on the first run — instead of the per-prompt
   half-rule; Tier-3 fails a named checkpoint and still runs the later phases. Grading
   is shape-aware (`assertion_results`, `"passed"` spellings) and an unparseable grading is
   *ungraded*, never a silent zero. Tier-1b scores a bare `Skill` call on a built-in's name
   (`code-review`, `security-review`) as *collided*, not a hit — a live probe showed the model
   calling `agentic-forge:code-review` namespaced, so this guards the scorer rather than corrects
   the baseline. The PR watcher returns *undetermined* for such a session, posts nothing and
   leaves the thread for the next poll. Connectors raise `ops.SourceUnavailable` instead of
   returning `[]`, and the deploy digest says "unknown — source unavailable (why)" instead of
   "healthy". `gh run list` has a timeout; an errored `gh pr list` fails the job; an unreadable
   comment list skips the "please rebase" post; an empty `gh pr view` is "unconfirmed".
4. **The watcher is bounded and audited.** One fixer attempt per thread, `≤ 0.8 × 1800 s /
   max_threads`; a watcher pass is spawned in its own process group and killed with it at the
   budget, so an aborted `claude` never keeps editing the checkout; every pass ticks and persists
   the queue before reporting; queue entries carry `failures`, the drop reason is true
   ("finished" or "tick budget spent: N of M polls failed"), and a checkout failure, a non-zero
   exit, a kill or a job failure is a forced diagnostics event.
5. **Guardrails: a depth table, segment discipline, an alternative in every message.** Roots,
   whole homes and OS trees block at any depth; paths inside `/home/<user>`, `/root`, `/var/tmp`,
   `/var/folders`, `$TMPDIR` are project paths. "Permissive" chmod is a grant to *others*.
   `is_commit_or_push` and `is_pr_merge` follow ADR 0054/0079: heredoc bodies stripped, quote-aware
   segments, the command word. A heredoc receiver is a token, not a substring (`ssh-notes.md` is a
   file). Every block message names what to do instead.
6. **Content: reachable, honest about absence, delivered without a remote.** Packs are reached by
   file path — `${CLAUDE_PLUGIN_ROOT}/skills/<pack>/SKILL.md`, `stacks.pack_paths` — never by
   name; a live `develop` session now reads `engineering-standards` and `python-patterns` from
   disk before delegating. Every phase skill has an explicit branch for an absent input: derive
   from the prompt and the repo, state the assumptions in the artifact's header, say what was
   missing, and never stop to ask when headless. `doc_delivery.proceed_plan` commits without
   pushing when there is no remote and pushes without a PR when `gh` is absent, saying so.
   `research` has `WebSearch`/`WebFetch` and no phantom skill; `marketing` forks `Explore`;
   `qa-test-strategy` delegates "plan only". Four descriptions changed, each same-length or
   shorter (the listing is at its ceiling): `deep-review` and `develop` no longer read as a price
   list — the cost inventory that produced ADR 0091's proportionality miss moved into the body,
   with a small-target path; `security-review` owns "SECURITY"; `research` lost the phantom.
   Shipped `SKILL.md` files no longer link into `docs/`, which does not ship.
7. **Eval content: a stand that carries what the prompt presupposes.** The `diagnostics-bundle`
   cases run against a seeded `./fake-home` (`--home` / `AGENTIC_FORGE_HOME`); the ten packs and
   `skill-factory` seed a manifest, a source file and an existing test (or a plugin skeleton)
   through the new `tree/` fixture layout; `ux-design` gets a design system to reference;
   `incident-response`'s prompts carry an incident; the Tier-1b stand seeds a `docs/knowledge/`
   vault; six Tier-2 prompts that dictated their finding now leave it to the fixture. In-window
   log records cannot be seeded statically (dates rot), so the bundle cases assert on old and
   undated seeds only. A test now checks that every `files` entry resolves and no placeholder
   remains.
8. **CI selects by positive list, and the summary names the step.** The Tier-1 step and the two
   model-backed jobs list the inputs that mean "the gate"; the summary says Tier-1b or the
   built-in condition ran when it did. Retracted ADR 0089 claims that still stood as fact in the
   schema, the settings, `configuration.md`, `guardrails.md`, the CHANGELOG and the ADR index are
   marked retracted; the index states the amendment convention this series has used since
   ADR 0090.

## Consequences

- One change set, seven areas, ~1,500 tests: the three shapes are now guarded by the same
  primitives everywhere — `hook_notice`/`hook_crash`, `SessionUndetermined`/`MAX_UNDETERMINED`,
  `SourceUnavailable`, the fixture `tree/` layout — instead of one fix per sighting.
- Trigger prompts changed for seven skills and descriptions for four, so Tier-1 re-ran on the
  merged tree with the new scorer: **17/17 at recall 1.000 / specificity 1.000**, 814 router
  calls. Two things the run itself taught: the first pass hit the usage limit after ~90 calls and
  the instrument reported fourteen skills as "never ran" rather than as zeros — the shape this ADR
  is about, seen working; and one `deploy-watch` should-not prompt ("fix the manifest") made the
  router go and look for a YAML that was not there on ten calls out of ten — a stand that
  presupposes, in the router's own lane — so it now carries the snippet and measures. The Tier-1b
  stand changed materially (referents, a vault, the absence branches), so its baseline of record
  (ADR 0093, 79/84) no longer describes this stand. The re-baseline, run on the released tree,
  reads **83/84 = 0.988** — sixteen of seventeen skills at 1.000, the one miss a `ux-design`
  session reading "what *are* the accessibility requirements?" as a lookup rather than a design
  request. Four things moved at once (prompts, descriptions, absence branches, the collided
  scorer), so it is a new baseline of record rather than a lift attributable to any one of them.
  The 0.80 floor stays: it was calibrated against model drift, not against the current value.
- Known and deliberately left: the daily deploy digest passes the repository *path* as the `gh`
  `--repo` slug, so with `gh` on PATH it now reports "unknown — source unavailable" honestly where
  it used to say "healthy"; the slug should come from the remote (a follow-up, not a shape).
- The field prediction of ADR 0092 is unchanged and still the next measurement: the next
  diagnostics bundle from a production repository, `Skill` against `Agent` counts.
