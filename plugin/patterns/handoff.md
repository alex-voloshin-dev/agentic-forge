# Pattern: file-based handoff

Phases of a workflow communicate by **writing artifacts the next phase reads**, not by
passing context in a single long conversation. This keeps each phase decoupled, auditable,
and resumable, and the artifacts double as project documentation (and, in Stage 3, knowledge
base seeds).

When the consumer of a handoff is a running peer session rather than a later phase, see
[fleet-coordination.md](fleet-coordination.md).

## Shape and location

Each artifact is a Markdown file with a **YAML frontmatter header**:

- The **header** carries the structured fields the next phase parses (status, lists, ids).
- The **body** carries the detail for humans and Claude.

Artifacts live in the target repo in the **feature's folder** and are committed: the folder the
repository already keeps for that feature, or `docs/sdlc/<feature-slug>/` when it keeps none
(below). The slug is a short kebab-case name for the feature (e.g. `search`, `oauth-login`).

### Where a feature's documents go

A repository with its own convention (features under `features/in-progress/<slug>/`, a central
decision series `adr-001`…`adr-066` beside a second one `ADR-G01`…`ADR-G14`, feature-local `adr/`
folders) must not get a second home for the feature or colliding ADR numbers. A repository's config
may only switch things off (ADR 0102/0103), so a phase **reads the convention from the tree**
before it writes, with one command (the phase passes the `--kind` of its own document:
`research`, `prd`, `design`, `plan`, `ux`, or `adr`):

```
python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" artifact-home --repo <worktree> --slug <feature-slug> --kind design
```

It prints one JSON object (`path`s relative to `--repo`, `/`-separated; `abs` ones absolute):

| Field | Meaning |
| --- | --- |
| `feature_dir`, `feature_abs` | Where the feature's documents go; the skills write it `<feature-dir>`. A directory named exactly `<slug>` that holds `prd.md`, `plan.md`, `design.md`, `tech-design.md`, `research-brief.md` or `ux-spec.md`; with several, the one holding the most, then the shallowest. With none, `docs/sdlc/<slug>`. |
| `detected`, `existing` | Whether `feature_dir` already existed, and the feature documents in it. |
| `documents` | One entry per kind (`research`, `prd`, `design`, `plan`, `ux`): `path` (the spelling on disk, e.g. `PRD.md`, else the plugin's name), `abs`, `arg` (`abs` quoted for a shell), `exists`, `format` (`handoff`: opens with a `---` frontmatter naming its `type`; `foreign`: anything else, a metadata table or another tool's header), `unsafe` when set, and `commands`: `handoff_load`, `external_review`, `status`, `diff`, `diff_check`, `diff_stat`, each `{"argv", "shell"}` with every path quoted. |
| `adr` | The decision series to continue: `dir`, `abs_dir`, `arg_dir`, `pattern`, `highest`, `next_id`, `next_file`, `scope` (`feature`: the feature's own; `shared`; `none`: no series, so `adr-<decision>.md` beside the design, as before), `create_dir` with `commands.mkdir`, `unsafe` when set, and the `series` seen, nearest first, with `series_count`. |
| `ambiguous`, `ambiguities` | Why the pick is not the only reasonable one: several folders named `<slug>`, a folder skipped for its name, equally near ADR series, a shared series beside feature-local ones, several spellings of one document, or a walk cut short by a cap (`truncated`). |
| `artifact` | With `--kind`: that document's entry (for `adr`, the next record's path). With `--path <file>` too, the document the user named, mapped into `--repo` (below). |
| `commands.feature_status` | `git status --porcelain` of the feature folder. |

**An ADR series** is the files of one directory below the top sharing a numbering: `adr-001-x.md`,
`ADR-G14-x.md` (a letter prefix, then two digits or more), or, in a directory named `adr`, `adrs` or
`decisions`, adr-tools' `0001-x.md` (never a dated `2024-01-15-x.md`). The feature's own series (in
its folder, or an `adr`/`adrs`/`decisions` directory directly in it) wins; otherwise the shared
series nearest the feature folder by path distance. Other features' own series are never
continued: when only they exist, the convention is feature-local and this feature's series starts
at 1, spelled and placed as most of theirs are. Records at the top of the repository are not a
series to continue (nothing may be written there).

The rules a phase follows:

- **Write into `<worktree>/<feature-dir>/`** — the document, its review rounds, and (architecture)
  the ADRs in `adr.dir` — and read upstream documents from there. `docs/sdlc/<feature-slug>/` is the
  fallback the command already returns, never a second home beside a detected one. The exception is
  `marketing`, whose briefs belong to no single feature: it keeps `docs/sdlc/<slug>/`.
- **Never put a path on a command line yourself.** A folder name is the repository's choice, and the
  main session may run in `bypassPermissions`. Run the printed `commands` verbatim, and where a
  command takes a path, pass the quoted `arg`. Folders are proposed only when every component of
  their path is letters, digits, `.`, `_` and `-` (not starting with `.` or `-`); anything else is
  skipped and named in `ambiguities`.
- **`unsafe` means stop.** A symlink, or anything but a regular file (a directory for `adr`), at or
  on the way to the path: never write through it; report it.
- **A path the user names** goes through `--path <file>`: an absolute path in any checkout of the
  repository maps to the same relative path under `--repo` (the worktree), never the checkout's
  copy; `exists: false` then means the worktree does not have it yet.
- **`ambiguous`:** interactive, show the `ambiguities` and ask which; headless, there is no one to
  ask, so take the command's pick, record it in the artifact's body as an `assumption:` naming the
  alternatives, and flag it in the summary. Several series with one clearly nearest is not
  ambiguous: use it, and name the others in the summary.
- **Never renumber or reuse an id.** Continue from `next_id`, one number per new record, in the
  series' own spelling.

The walk is bounded (depth 12, 200,000 entries; `truncated` says either cap cut it), reads the
shallow tree first, never follows a symlink, and skips hidden directories (`.git`,
`.claude/worktrees`), dependency and build output (`node_modules`, `vendor`, `build`, `dist`,
`target`, …, unless the directory is named exactly `<slug>`) and any nested repository. The
role-scope hook reads the same predicates: outside `docs/`, the `architect` role may write only
`tech-design.md` or a decision record into a feature folder or ADR directory that already exists,
so a phase whose `adr.create_dir` is true runs `adr.commands.mkdir` itself before it delegates, and
it hands the role absolute paths.

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

**When the predecessor is in a foreign format.** A repository's own PRD (a metadata table such as
`| **Status** | … |` instead of YAML frontmatter; `artifact-home` reports `format: foreign`) has no
header for `handoff-load` to validate and no `review_decision` to read, so `handoff-load` is not its
gate: it would refuse every such document. A phase that reads one (`architecture`, and `plan` for
acceptance context) **builds from it when the user points at it** — names it, or asks for this
feature whose folder holds it — reads its body as the requirements, and **says so**: the artifact
it writes records in its body that its input was a foreign-format PRD whose readiness was not
machine-checked, naming its path and its latest review round (`review-prd-<n>.md` in the feature
folder, the highest `iteration`) if there is one. A round whose `verdict` is still `changes` means the amendment escalated: surface that
and do not build on it unasked. `develop` reads only `plan.md` and `tech-design.md`, which the
plugin writes in its own format, so a foreign PRD reaches it only through them.

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
[worktree.md](worktree.md) (where the `develop` phase reads `plan.md`), and
[fleet-coordination.md](fleet-coordination.md) (handing work to a running peer session).
