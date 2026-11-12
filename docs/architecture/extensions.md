# Plugin extensions (post-Stage-7)

After the five layers (L0–L4) and the SDLC domains were built, a set of **cross-cutting plugin
extensions** were added — configuration, model routing, and two outward-facing review/automation
seams. They are not a new layer: each plugs into the existing engine, guardrails, or eval gates.
This document is their narrative home; the per-decision detail lives in the linked ADRs.

All of these follow the same house style as the connectors: a **pure, fully-tested core plus a thin
injected seam** for the live call, the seam excluded from coverage. All are opt-in **except the
external reviewer**, which is on by default (ADR 0057) but degrades to a no-op when its CLI is absent
— so it changes default behaviour only where `codex` is installed.

## Configuration (`settings.py`, ADR 0041 / 0049)

One resolver for the plugin's knobs, over a layered precedence:

```
built-in DEFAULTS  <  user-level ~/.agentic-forge/config.json  <  per-repo .agentic-forge/config.json  <  env vars
```

What the checkout must not decide is taken out of the repo file before that merge, not restored after
it: the reviewer's `command`, `isolated`, `model` and `effort` (ADR 0100), `state.in_repo` and
`knowledge.allow_external_vault` (ADR 0102), and everything under `pr_watcher` but `enabled: false`
(ADR 0103).

So a user sets defaults once in their home, a repo overrides them per-project, and CI / one-off env
vars still win. Both files are validated against [`config.schema.json`](../../plugin/schemas/config.schema.json).
`resolve()` **never raises**: a missing file is defaults; a malformed file is defaults + a one-line
stderr warning. `jsonschema` is imported lazily and is optional, so a guardrail hook can resolve
settings under a bare `python3` without the plugin's third-party deps (ADR 0050). Every other
extension here reads its on/off switch and parameters from this resolver. Full key reference:
[configuration.md](../configuration.md).

## Model tiering & runtime routing (`models.py`, ADR 0043 / 0046)

Cheaper models (sonnet / haiku) for simpler work, the strongest (opus) for hard work. Tiering is
**opt-in** via `settings.models` and **validated by the eval gates** — Tier-1 / Tier-2 are
model-dependent, so a downgrade only ships where the component still passes its gate at the cheaper
tier. With an empty `settings.models` every component resolves to the global `default` (no behaviour
change). Runtime routing (ADR 0046) closes the loop: `models.frontmatter_model(name)` maps the
validated tier onto each agent's `model:` frontmatter, and Tier-0 (`validate_agent`) **fails** if an
agent's committed `model:` drifts from the validated policy — so live `Task` delegation can never run
on an unvalidated tier. `dev/sync_models.py` regenerates the frontmatter from the policy.

## External reviewer seam (`external_review.py`, ADR 0042 / 0057 / 0060 / 0100)

A different model is an independent review lens — it catches what a same-family `reviewer` pass
misses (see [adversarial-review.md](../../plugin/patterns/adversarial-review.md)). This seam runs a
third-party reviewer CLI (e.g. `codex`) as that extra lens: a pure `build_prompt` / `parse_review`
core plus a thin subprocess seam that **never raises** and degrades gracefully when the CLI is
absent. Gated by the `external_reviewer.*` settings. **On by default (ADR 0057)** and
**auto-wired** as an extra lens into **every workflow that writes a reviewable deliverable** —
`develop`'s multi-aspect code-review gate (`--kind code`, findings inside the bounded N = 3 loop),
`product`'s skeptic pass (`--kind product`), `architecture`'s (`--kind technical`) and `plan`'s
(`--kind plan`) since ADR 0060, `research`'s (`--kind research`) and `ux-design`'s (`--kind ux`)
since ADR 0061, and `marketing`'s claims pass (`--kind marketing`) since ADR 0062.
There is **one `KINDS` entry per review-criteria set** — the failure modes of what a phase hands off,
so a router whose deliverables share one failure mode needs only one (tested: the set is exact, the
criteria distinct) — because an unknown kind falls back to the code criteria, wrong for a brief,
spec, or design. In every case the findings fold into that phase's bounded loop, whose exit
is the shared `review_loop_decision`. codex is driven by *our* strict per-kind prompt (`build_prompt`) and runs
`exec --sandbox read-only`, so its findings aggregate with the internal aspects into one verdict.
This is the one extension whose default is **on**, not opt-in: the safety valve is graceful skip
when `codex` is absent (the common case) — so it only reaches a third party where the CLI is
installed. It sends the target to that third party, so **set `enabled: false` on secret-bearing
repos**. Driver: `plugin/bin/external_review.py`.

**Skips and failures say why (ADR 0100).** `review_outcome` returns a `ReviewOutcome`: `reviewed` with
the review; `skipped` with a reason in `SKIP_REASONS` (`missing-cli`, `command-not-configured`,
`disabled`: there was no reviewer to ask); or `failed` with a reason in `FAILURE_REASONS` (`timeout`,
`process-failure`, `invalid-output`, `isolation-unsupported`: the reviewer was there and enabled and the
attempt produced no review). Each carries a short detail, redacted before it is capped. Neither a skip
nor a failure has a verdict, so neither can read as approval. The difference is what the caller does
with it: a skip is expected and the round goes on, while a failure is a lens that dropped out, so the
CLI exits `3` for it (`0` for a skip, `1` for `changes`) and the workflows record it in the round and
report it to the user instead of treating it as a skip.

**How the call is made.** `_argv` builds `codex exec --sandbox read-only --skip-git-repo-check
[isolation flags] [--model] [-c effort] -`, and `_run_cli` writes the prompt to the process's stdin
(`subprocess.run(input=...)`), which `codex exec -` reads as the prompt. The prompt used to be the last
argv element, which failed with `E2BIG` for a diff over 128 KiB, the Linux cap on one argument, and
could not hold a NUL byte at all. Stdin has no such cap, and since it is a pipe holding only the prompt,
the caller's own stdin still never reaches the reviewer. `--skip-git-repo-check` is there because codex
refuses to start outside a trusted git repo, and `develop` writes the diff to a scratch directory and
may run from anywhere. It does not loosen the sandbox or mark any directory trusted. `-C <dir>` was not
added: the subprocess `cwd` already names the directory, and `-C` alone would not get past the same
check. The `cwd` is still `--repo` (the caller's cwd by default), so a review run from the repo keeps the
repo as context. codex echoes the prompt to stderr, so a failed run's detail drops every line that is
also a prompt line before it is cut to its tail. `review()` wraps it for the skills, which did not change. It runs nothing when
`enabled` is false (`disabled`), and refuses a `command` other than the configured one
(`command-not-configured`) without running it. The operator's CLI calls `review_outcome` directly, so
`--command` and `--force` still work. **Isolation is opt-in** (`external_reviewer.isolated`, with `model` and `effort`): it adds
`--ignore-user-config --ephemeral` after `exec --help` confirms both flags, and skips otherwise rather
than falling back. `review()` reads these settings through `settings.resolve`, so the setting reaches
the skills too. Every flag is fixed in `_argv`; there is no free-form args setting. **`command`,
`isolated`, `model` and `effort` are user-level only:** a repo file's values are removed before the
merge, because the repo is what gets reviewed. A repo that picked the executable could have a program
of its choosing run on the operator's machine and forge the verdict, a repo's `isolated` would drop the operator's whole CLI config, and a repo's
`model` or `effort` could weaken its own review. A user-level `enabled: false` also holds against a repo,
because content goes to a third party. `model`, `effort` and `command` are
validated in code rather than by a schema pattern: `jsonschema` may be absent, and a schema failure
would drop the whole file, `isolated` included. This is not a stronger sandbox than those flags provide.

**Reading the reply (ADR 0100).** The reviewer may quote the target, so any review-shaped `changes` in the
reply decides the verdict, with the findings of every `changes` object, de-duplicated. An approve is refused, as
`invalid-output`, when the raw reply also says `changes` in a form that did not decode, or when too many
openings failed to decode for the rest to be read. Every finding field
loses terminal escapes and control characters and has secrets redacted before it reaches the terminal or
`review.md`. The CLI refuses a symlink for `--target` and `--out`, and a symlinked directory inside the
repo on the way to either.

## PR watcher (`pr_watch.py`, ADR 0044 / 0045)

Parse a GitHub PR's review state from the `gh` GraphQL JSON and drive a **bounded** fix loop:
plan a response to each review thread, build the `gh` / `git` commands, optionally run an injected
`fixer`. Pure parsing / planning over the JSON; the live `gh` / `git` writes and the model fix are
thin injected seams (excluded from coverage, like the connectors). It is off by default and
dry-run unless the caller passes a live `fixer` / `gh_exec` / `push`, and it **never force-pushes** —
there is deliberately no force builder. **Merging is the one reversal (ADR 0063):** the watcher can
now carry a PR to done — triage each review comment (valid → fix through the `software-engineer` +
bounded review loop; invalid → reasoned refutation, thread left open), resolve conflicts, and merge
once the pure `merge_readiness` gate opens (not draft, checks green — *no CI at all blocks*, no
unresolved threads, `MERGEABLE`). An external reviewer's window is the poll interval, not a separate
timeout: a fresh PR has `PENDING` checks, so the earliest merge is one `poll_seconds` after opening.
It is gated by
the user-level `pr_watcher.auto_merge`, **off by default**, and never merges in the same pass that pushed a fix
(the green checks describe the pre-fix commit). The merge is pinned to the commit the gate read. The scheduled driver
reads its settings once, never fetches a fork, runs each pass in a temporary detached worktree so the operator's tree and
HEAD are not involved. Its fixer session has no settings, five tools and the tree as its limit, only threads from people with write access
or reviewer apps the operator lists reach it, and it pushes before it replies (ADR 0103). A `PostToolUse` hook notices `gh pr create` and says what
can follow: `/pr-watch` is a manual command for the user, and an agent checks the PR with `gh` itself.
It only informs — a guardrail must not silently launch an agent that can merge. Two surfaces:
the scheduled multi-repo driver `plugin/bin/pr_watch.py` (maintainer/CI), and the **`pr-watch` skill**
(off-listing, manual `/pr-watch`) — interactive single-PR babysitting over the same lib, added
after field bundles showed users hand-rolling `gh pr view` polling loops. The skill reads one PR through
`af.py pr-state` (ADR 0104): a fork is read-only there too, a person's permission is asked, and `push` and `merge` are
commands it prints for the session to run.

## Related, documented elsewhere

- **Ralph loop** (`ralph.py`, ADR 0048) — bounded autonomous iteration; see
  [the engine overview](overview.md) and [`patterns/ralph.md`](../../plugin/patterns/ralph.md). It
  is CLI-driven (`dev/ralph.py`), not composed into a skill.
- **Self-diagnostics** (`diagnostics.py`, ADR 0039) — the plugin's own error/anomaly channel; see
  [scheduling & observability](scheduling-observability.md).
- **Review-loop non-convergence scan** (ADR 0040) and **hook import safety** (ADR 0050) — guardrail
  hardening; see [guardrails](guardrails.md).
