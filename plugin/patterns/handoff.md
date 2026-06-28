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
| `research-brief.md` | `research` skill → built-in `Explore` | `type, feature, status, date, sources[]` |
| `prd.md` | `product` skill | `type, feature, status, goals[], non_goals[], metrics[], acceptance[]` |
| `tech-design.md` + `adr-*.md` | `architecture` skill → `architect` | `type, feature, status, decisions[], components[], risks[]` |
| `plan.md` | `plan` skill → built-in `Plan` | `type, feature, status, tasks[] (id, deps), checkpoints[], deferred[]` |
| `review.md` | `code-review` skill → `reviewer` | `type, target, iteration, verdict, findings[]` |
| `test-strategy.md` | `qa-test-strategy` skill → `qa-engineer` | `type, feature, status, test_levels[], scope, risks[], cases[]` |
| `release.md` | `release` skill | `type, feature, status, version, changelog[], bump, breaking[]` |
| `incident.md` | `incident-response` skill | `type, severity, status, impact, timeline[], remediation[]` |
| `deploy-status.md` | `deploy-watch` skill | `type, environment, pipeline, alerts, action` |
| `market-brief.md` | `marketing` skill (research) | `type, feature, status, segments[], competitors[], sources[]` |
| `marketing-strategy.md` | `marketing` skill (strategy) | `type, feature, status, positioning, channels[], messaging[], metrics[]` |
| `ux-spec.md` | `ux-design` skill | `type, feature, status, flows[], screens[], accessibility` |
| `onboarding.md` | `repo-onboarding` skill | `type, feature, status, components[], entry_points[], conventions[], risks[]` |

`status` is recommended to be one of `draft | in-review | approved | final | superseded`
(the schema accepts any non-empty string). `verdict` is
`approve | changes`. Finding `severity` is `blocker | major | minor | nit`.

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
slug. Use list fields for anything the next phase iterates over; keep prose in the body.
Validate before committing — a malformed header breaks the consumer.

## Consuming an artifact

Read the predecessor's **header** for structured fields and its **body** for rationale. The
shared helper `agentic_forge.handoff` loads and validates headers against per-type schemas:

```python
from agentic_forge.handoff import load_artifact

prd = load_artifact("docs/sdlc/search/prd.md", expected_type="prd")
for goal in prd.header["goals"]:
    ...
design_body = prd.body  # full markdown after the frontmatter
```

`load_artifact` / `parse_artifact` raise `HandoffError` on a missing file, malformed
frontmatter, or a header that fails its schema (wrong `type`, missing required field, bad
enum). Use `validate_header(header, expected_type=...)` to get the list of problems without
raising, and `schema_for(type)` to inspect a schema.

## Why this pattern

- **Decoupled:** a phase only needs its predecessor's artifact, not the whole transcript.
- **Auditable & resumable:** artifacts are committed, so work can stop and restart.
- **Typed at the seams:** schema validation means a downstream phase can trust the fields it
  parses instead of re-deriving them from prose.

See also: [review-loop.md](review-loop.md) (the `review.md` artifact drives the loop) and
[worktree.md](worktree.md) (where the `develop` phase reads `plan.md`).
