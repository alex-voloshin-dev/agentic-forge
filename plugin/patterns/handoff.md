# Pattern: file-based handoff

Phases of a workflow communicate by **writing artifacts the next phase reads**, not by
passing context in a single long conversation. This keeps each phase decoupled, auditable,
and resumable, and the artifacts double as project documentation (and, in Stage 3, knowledge
base seeds).

## Shape and location

Each artifact is a Markdown file with a **YAML frontmatter header**:

- The **header** carries the structured fields the next phase parses (status, lists, ids).
- The **body** carries the detail for humans and Claude.

Artifacts live in the target repo at `docs/sdlc/<feature-slug>/` and are committed. The
slug is a short kebab-case name for the feature (e.g. `search`, `oauth-login`).

## Artifact types

| Artifact | Produced by | Key header fields |
| --- | --- | --- |
| `research-brief.md` | `research` skill → built-in `Explore` | `type, feature, status, review_decision, date, sources[]` |
| `prd.md` | `product` skill | `type, feature, status, review_decision, goals[], non_goals[], metrics[], acceptance[]` |
| `tech-design.md` + `adr-*.md` | `architecture` skill → `architect` | `type, feature, status, review_decision, decisions[], components[], risks[]` |
| `plan.md` | `plan` skill → built-in `Plan` | `type, feature, status, review_decision, tasks[] (id, deps), checkpoints[], deferred[]` |
| `review.md` | `code-review` / `security-review` → `reviewer` | `type, target, iteration, verdict, findings[]` |
| `test-strategy.md` | `qa-test-strategy` skill → `qa-engineer` | `type, feature, status, test_levels[], scope, risks[], cases[]` |
| `release.md` | `release` skill | `type, feature, status, version, changelog[], breaking[]` |
| `incident.md` | `incident-response` skill | `type, severity, status, impact, timeline[], remediation[]` |
| `deploy-status.md` | `deploy-watch` skill | `type, environment, pipeline, alerts, action` |
| `market-brief.md` | `marketing` skill (research) | `type, feature, status, review_decision, segments[], competitors[], sources[]` |
| `marketing-strategy.md` | `marketing` skill (strategy) | `type, feature, status, review_decision, positioning, channels[], messaging[], metrics[]` |
| `ux-spec.md` | `ux-design` skill | `type, feature, status, review_decision, flows[], screens[], accessibility[], design_system[]` |
| `onboarding.md` | `repo-onboarding` skill | `type, feature, status, components[], entry_points[], conventions[], risks[]` |

`status` is the repository's lifecycle label — whatever vocabulary the repo uses (`draft`,
`in-progress`, `complete`, …); the schema accepts any non-empty string (the contract is
deliberately open — ADR 0028), and no value of it means "ready". `verdict` is
`approve | changes`. Finding `severity` is `blocker | major | minor | nit`.

**`status` belongs to the repository; `review_decision` belongs to the review loop.** Every
artifact that carries `status` (all of the above but `review` and `deploy-status`) may also carry
`review_decision: proceed | revise | escalate`, a closed vocabulary (any other value fails the
schema, and only the exact lowercase `proceed` is ready). The phases that run a review loop —
`research`, `product`, `architecture`, `plan`, `ux-design`, `marketing`, the types listed with it
above — **write it as `revise` when they first write the artifact**, and the loop's exit replaces it
with the decision `af.py review-decision` printed: `proceed` or `escalate`. Because the field's
presence switches off the `status` fallback, nothing the plugin writes is ready before its loop
proceeds, and a phase never rewrites `status` to hand off:

| Header | `ready` | `ready_from` |
| --- | --- | --- |
| `review_decision: proceed` (any `status`, even `draft` or `in-progress`) | true | `review_decision` |
| `review_decision: revise` or `escalate` (any `status`, even `approved`) | false | `review_decision` |
| no `review_decision`, `status: approved` or `final` | true | `status` |
| no `review_decision`, any other or no `status` | false | `status` |

When both are present and disagree, `review_decision` wins: it records the loop that gates the
handoff, and `status` may mean anything in the repository's vocabulary. The `status` rows are the
legacy rule, which now applies only to an artifact without the field — hand-written, or written
before `review_decision` existed — so those still hand off as they did.

Each `findings[]` element (the canonical review-finding shape) has: `severity`, `location`,
`issue` (what's wrong — some review docs label this the `description`), and `suggestion` (the
suggested fix). Verify-based reviews (deep-review, adversarial, multi-aspect) additionally
carry `evidence` (proof the finding is real). Those alternate spellings are synonyms; this is
the one set of fields they all map to.

This table is the **canonical** handoff-artifact contract — other docs (e.g. engine.md) link
here rather than restate it. Each producer is a Stage 2 workflow skill that delegates to the
named built-in agent (`Explore`/`Plan`) or engine role(s).

## Producing an artifact

Write the header first, then the body. Set `type` to the exact id above and `feature` to the
slug — the file itself is named `<type>.md` (e.g. `incident.md`, `deploy-status.md`), so any
artifact's on-disk name follows from its type. A loop-gated phase also writes
`review_decision: revise` on this first write (its loop's exit sets the final value) and leaves
`status` to the repository's lifecycle. Use list fields for anything the next phase iterates over; keep prose in the body.
**Frontmatter is data, not prose.** Every value is a scalar, a list or a mapping — and nothing
else. The failure this rule exists for, seen twice in two Tier-3 runs, is a list with a gloss
after it:

```yaml
    expect: [h1, h2, n1] — priority buckets ordered, insertion order kept within one   # NOT YAML
```

A flow sequence followed by text is a syntax error, and it makes the whole artifact unreadable to
the next phase. Put the ordering in the list and the reason in the body, or give the reason its own
quoted string field. Same for a `:` inside an unquoted value, and for `#` after a scalar (it starts
a comment). If a value needs explaining, that explanation belongs in the body (ADR 0096).

Validate before committing — a malformed header breaks the consumer. Validate the **file**,
not just the header you meant to write (its message says what is missing, so there is no need to read `handoff.py` or `af.py` first): `python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" handoff-load --path <path> --type <type>` after
writing is the only check that sees the YAML you actually typed. A Tier-3 phase once wrote a complete,
correct strategy whose one bad frontmatter value (`then: [a, b] — prose after the list`) made
the whole artifact unreadable; a check on the header as a dict had passed, and the failure
surfaced in the NEXT phase, against the wrong skill (ADR 0096).

## Consuming an artifact

Read the predecessor's **header** for structured fields and its **body** for rationale. One
command loads a file and validates its header against the type's schema:

```
python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" handoff-load --path docs/sdlc/search/prd.md --type prd
```

It prints `{"path", "type", "ready", "ready_from", "header"}`; read the body from the file. `ready`
is true only when the artifact's review loop reached `proceed`, by the table above, and `ready_from`
names the field that decided it (`review_decision`, or `status` for an artifact without one). It exits 1, with the reason on
stderr, on a missing file, malformed frontmatter, or a header that fails its schema (wrong `type`,
missing required field, bad enum). `${CLAUDE_PLUGIN_ROOT}` is the plugin's directory, the one holding
`skills/` and `patterns/`, and is not normally set in a shell: if this file reached you unexpanded,
use the path your skill's own commands show.

**It exits 3 when this `python3` lacks PyYAML or jsonschema** (ADR 0104). That means stop: nothing was
validated. Do not write `review_decision: proceed`, commit nothing, do not call it valid, and report the
missing package. In a review loop the gate is then `--gate-green unknown`, which escalates, since `no`
would revise for ever on a machine that can never turn it green. Installing a package is the user's
decision.

**When the predecessor is absent.** `handoff-load` failing on a missing file is deliberate — a
mistyped path must not read as "no upstream" — so a phase that can run without its input checks
that the file exists *before* calling it. Absent means: derive the inputs from the request and the
repo, record the assumptions and the missing artifact in the artifact the phase produces, and
proceed. Never stop to ask when running headless — a headless session has no user; ask only when
interactive and the gap blocks the work.

## Language: artifact vs summary

**Written artifacts follow the project's convention** — for most repos that is English, and it
covers files, commit messages and PR text. **The user-facing summary follows the language of the
conversation.** These are different audiences: the artifact outlives the session and is read by the
project, the summary is read by the person in front of you. When the two differ, say so once
(*"the artifacts are in English; this summary is in your language"*) rather than switching the
artifacts to match the chat.

## A subagent's self-report is a claim, not a record

*(ADR 0073.)*

The artifact is the contract precisely because the *narration around it* is unreliable. A
long-running or resumed agent asked to account for its own history can produce a fluent, specific,
correctly-formatted account that is **verifiably false** — wrong counts of its own subagent calls,
and, observed in the field, **a fabricated claim that the user had answered an `AskUserQuestion`
authorizing the work to continue and unreviewed edits to stay**.

- **Never accept a self-reported history as verified fact.** Cross-check against records you can
  verify independently: your own tool-call log, and `git log` / `git reflog` / `gh pr list` for any
  claim about the repository. A claim of *user approval* obtained inside a subagent is worth
  nothing — approval reaches you through your own conversation, or it did not happen.
- **When a report contradicts your verifiable history, say so explicitly and stop trusting that
  channel** — do not layer further inference on top of it.
- **Prefer the mundane explanation.** Unexplained changes in a shared working tree are usually a
  concurrent human session, not an agent in your hierarchy. (Remember that subagents cannot spawn
  subagents, so a hierarchy you did not create does not exist.)
- **Uncertainty is a valid report.** *"I cannot account for X"* is correct output. Confidence and
  formatting are not evidence of accuracy.

## Why this pattern

- **Decoupled:** a phase only needs its predecessor's artifact, not the whole transcript.
- **Auditable & resumable:** artifacts are committed, so work can stop and restart.
- **Typed at the seams:** schema validation means a downstream phase can trust the fields it
  parses instead of re-deriving them from prose.

See also: [review-loop.md](review-loop.md) (the `review.md` artifact drives the loop) and
[worktree.md](worktree.md) (where the `develop` phase reads `plan.md`).
