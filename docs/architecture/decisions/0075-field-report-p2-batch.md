# 0075 — Field-report P2 batch: secret exposure, ground truth, and shared-tree hygiene

**Status:** Accepted (implemented)
**Date:** 2026-07-26
**Completes:** the 2026-07-26 field report (AF-11 … AF-16, plus the documentation half of AF-04).

## Context

The remaining findings from the field report, taken as one batch. They share no single mechanism,
but they do share a failure mode: **the plugin trusted a source that only looked authoritative** —
a prefix filter, a memory of a file, a decision record, an untracked file, a green unit test.

The one code change here is AF-12; everything else is instruction, because everything else happens
inside a model's judgment where no hook can see it.

## Decision

### AF-12 — block environment dumps on remote hosts (the only code change)

A `printenv` on a production pod, filtered by a feature-flag prefix, matched a variable whose name
*extended into* a credential — `SCORING_VNEXT` matched `SCORING_VNEXT_CRUX_API_KEY` — and printed
the secret into the transcript.

`guardrails.classify_command` now blocks a **bare** `printenv` / `env` / `set` that reaches a
remote host through `kubectl|oc exec`, `docker|podman|nerdctl exec`, `docker compose exec`, `ssh`,
`fly ssh` or `heroku run`. Four deliberate narrowings keep it from becoming friction:

- The dump must appear **after** the remote marker, so `grep ssh printenv.txt` is untouched.
- **Bare only** — an argument means an exact lookup (`printenv PGHOST`), and `env VAR=1 cmd` /
  `set -e` are wrappers, not dumps.
- **Local dumps are not this rule's business.**
- A downstream **redaction filter** (`| grep -ivE 'KEY|SECRET|PASSWORD|PWD|TOKEN|CRED'`) makes it
  pass — that is the documented remedy, so blocking it would be perverse.

This **blocks rather than warns**: disclosure is irreversible, and by the time a warning prints the
secret is already in the transcript. Both safe forms are one edit away.

### AF-11 — read the original before a behaviour-changing corrective (`code-review`)

Reviewing a faithful-migration diff, a reviewer answered *"what did the original do?"* from memory
of an earlier partial read and issued a wrong, behaviour-changing correction. The rule: read it —
`git show <base>:<path>` — before sending any corrective that changes behaviour. Memory of a
partial read is not ground truth, and neither is the pre-image of a truncated diff hunk.

### AF-13 — no mutating requests to production during QA (`qa-test-strategy`)

QA verification issued live `POST`s against rate-limited public production endpoints. Each call
consumed a real quota unit and warmed a production cache keyed by the target, which then skewed the
CI runs asserting on the same endpoints. Verification is now explicitly read-only against
production; a genuinely required live mutation needs explicit human authorization and a named
cleanup step.

### AF-14 — a decision record states an intent, not a deployment (`knowledge`)

A record with `status: current` described a provider deprecation that was **never implemented** —
the provider was still wired and in active use, and the record was believed and acted on for two
months. The discrepancy was found only by grepping the config the decision claimed to change.

Recall now says: `status: current` means the decision stands, not that it shipped; before acting on
a note asserting a code/config/infra fact, verify against the artifact it names, and **surface any
disagreement rather than silently preferring either source**. Capture gets the complementary rule —
name the artifact a decision changes, so verification is one grep instead of an investigation.

### AF-15 — the working tree is shared with a human (`develop`)

Three incidents, one theme. **Untracked ≠ new**: an untracked file is often a stale snapshot of work
already merged upstream, and committing it silently reverts newer content (a lifecycle rename hides
this well) — diff against the base first. **Don't commit files the user copied in**: their next
`git pull` aborts. **Re-check after any pause**: `git status --short` with no path narrowing, and
re-read files before concluding, because the user commits, switches branches and prunes
concurrently.

### AF-16 — language follows the audience (`handoff`, `doc-delivery`)

Skills returned every user-facing summary in English regardless of the conversation's language,
forcing manual restatement on every invocation. The split the user wants preserved: **artifacts
follow the project's convention** (files, commits, PR text — usually English), **the conversational
summary follows the user's language**. When they differ, say so once instead of switching the
artifacts.

### AF-04 (documentation half) — the gate blocks the whole command

The preferred fix — distinguishing *"gate failed"* from *"gate could not run"* — **already shipped**
in ADR 0058/0059: `gate_unrunnable` plus exit codes 126/127 downgrade environment breakage to a
recorded `anomaly` and fail open. What was missing is the constraint itself: the gate is
`PreToolUse`, so it blocks the *entire* Bash command before any part of it runs, and a prerequisite
the gate needs (`ln -s … node_modules && git commit …`) can never be established in the same
command. Now documented in `guardrails.md`, with the remaining option — scoping the gate to the
staged diff — recorded as **not built**.

## Consequences

- One real secret-disclosure path is closed at the hook layer, with the escape hatches that keep it
  usable.
- Four *"I already know this"* shortcuts — memory of a file, a decision record, an untracked file,
  a green unit test — now have an explicit "go read the ground truth" step attached.
- Summaries will arrive in the user's language while the repo stays English. If a skill ever writes
  an artifact in the chat language, that is this rule misapplied, not the intent.
- **Instruction-level again** (except AF-12). Five of these seven have no gate; they will hold only
  as long as the bodies that carry them are read.
