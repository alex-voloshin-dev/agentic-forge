# Pattern: knowledge recall (read the vault to enrich a phase)

`${CLAUDE_PLUGIN_ROOT}` below is the plugin's directory, the one holding `skills/` and `patterns/`, and is not normally set in a shell: if this file reached you unexpanded, use the path your skill's own commands show.

Before a workflow phase produces its artifact, **recall the project's relevant prior decisions**
from the knowledge vault (`docs/knowledge/`) so it builds on what's already settled instead of
re-deriving it. This realizes the constitution's "workflows … read [the vault] to enrich their
context" (ADR 0033 — `docs/architecture/decisions/0033-knowledge-recall-in-spine.md` in the
agentic-forge repository, not shipped with the plugin).

## When

Every SDLC spine phase (`research → product → architecture → plan → develop → code-review`), at the
**start** (while reading inputs). Domain skills may adopt it too.

## Who recalls: the spawning session

**The session that runs the skill recalls; the roles it spawns receive the hits.** A subagent
cannot call the project's MCP tools (and the read-only roles are refused every MCP tool), and only
`software-engineer` and `qa-engineer` have a shell. Left to recall for themselves, roles grep the
docs and read whole Markdown files: measured over 19 hours, 20 subagents ran 0 searches, 107 doc
greps and 38 whole-file `.md` reads in a repository that had a search server. The skill's own
session has the project's MCP tools and a shell, so it does the search once and briefs every role.

- **Use the project's own search when it has one**: a search server **the repository itself
  configures** in its `.mcp.json` (e.g. a project `knowledge-search` server), or a search command
  or server the repository documents in its `AGENTS.md` / `CLAUDE.md`. It knows the project's
  documents better than any generic ranking.
- **A user-level connector is not the project's search**, whatever its name says: a cloud
  connector (Notion, Google Drive, a web search) comes from the user's account, not the
  repository, and searches other data. Do not recall through one.
- **Otherwise use `vault-recall`** (step 1 below) — the fallback that works in every repo with a
  vault.
- **Pass the top hits in the `Task` prompt**, bounded: the top 5-8, each a path plus one line on
  why it matters to this unit. Never paste whole files into the prompt.
- **A role may still `Read` the cited files**: the hits are pointers, not the content. A role
  briefed without hits (the vault was empty, nothing matched) proceeds without them.

## How

1. **Recall.** Query the project's own search (above), else the vault for notes relevant to the
   feature/topic — `python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" vault-recall --repo . --query '<keywords, letters and digits only>'`
   (ranked) or the `knowledge` skill. Use the phase's subject as the query (the feature slug + the
   phase's concern, e.g. "auth", "rate limiting"). Notes in every folder of the vault are ranked
   (`decisions/`, `learnings/`, ...), and each result's `path` is the file to read.
1b. **Brief the roles.** Every `Task` the phase spawns carries the top hits (paths + one line why),
   as above; the role does not recall again.
2. **Factor in.** Let recalled decisions shape the output; don't silently contradict a settled
   decision — call it out if you must diverge.
2b. **A decision record states an intent, not a deployment.** `status: current` means the decision
   stands, not that it shipped. Before acting on a note that asserts a **code, config or
   infrastructure fact**, verify it against the artifact it names — grep the config file, the
   manifest, the flag. If they disagree, **surface the conflict**; do not silently prefer either
   source. Field case: a `current` record described a provider deprecation that was never
   implemented — the provider was still wired and in active use, and the record was believed and
   acted on for two months.
3. **Cite.** When a choice leans on a note, reference it (`[[note]]`) so the trail is auditable.
4. **Capture back (optional).** New durable decisions the phase makes are candidates for the
   `knowledge` skill to save.

## Degrade gracefully

If the project has no search of its own and the vault is absent or empty (a greenfield repo),
recall is a **no-op** — never block the phase, and spawn the roles without hits.

## Composition

- Retrieval is the project's own search when it has one, else `vault-recall` / the `knowledge`
  skill; the vault is seeded by `repo-onboarding`.
- [fan-out-fan-in.md](fan-out-fan-in.md) briefs each unit with the hits this step produced.
- Used by the spine phase skills; it emits nothing of its own — it enriches the phase's existing
  output and handoff artifact.
