# 0051 — GitHub: server-side gating + a single MCP access boundary

Status: Accepted — **plan**; implementation staged (no code changed yet). Supersedes the local
`commit_gate` portion of 0019; refines 0044 / 0045 (PR watcher) and the GitHub side of 0021
(ops connectors). The deny-list portion of 0019 is **unaffected**.

## Context

GitHub is currently reached from many places, with control split between the local plugin and
nothing on the server:

- **Local guardrail hooks** (matcher `Bash`, ADR 0019): `commit_gate.py` runs the fast Tier-0/lint
  gate before a `git commit`/`git push`; `security.py` blocks force-push to a protected branch (plus
  a deny-list of destructive shell commands).
- **Deterministic library seams** that shell out to `gh`/`git`: `connectors.py` (`gh run list`),
  `pr_watch.py` (`gh api graphql`, `git push`), `release.py` (`git log`), `spine_e2e.py` (`git`
  fixtures), and the dev CLIs.
- **My own ad-hoc `Bash`** (`gh` / `git`) during a session — the widest surface of all.

Two things changed the trade-off. First, the repo now has **server-side protection**: a `master`
ruleset that requires the `Tier 0 (static gate)` CI check green + a PR before merge, forbids
force-push / deletion, and enforces linear history (set after this repo went public). Second, the
**GitHub MCP server** gives the model a single, named, per-tool access surface to GitHub.

So the local `commit_gate` now **duplicates** the server gate, GitHub contact points are **scattered**,
and there is **no fine-grained control** over what GitHub operations the model (or a given agent
role) may perform. This ADR moves gating to the server and consolidates model access behind one MCP
boundary, while being honest about what cannot move.

## Decision

Shift GitHub control from the local plugin to the server + a single MCP boundary, in four parts.

### 1. Server-side gating is the source of truth; drop `commit_gate`

`ci.yml` (`Tier 0 (static gate)`) + the `master` ruleset are the authoritative gate: nothing red
merges to `master`, and PR-flow is mandatory. The local `commit_gate.py` hook is **removed** — it
only bought earlier local feedback, which the server now guarantees after push. The git-specific
half of `security.py` (force-push / branch rules) is now **redundant with the ruleset**
(`non_fast_forward`, `deletion`, `required_linear_history`) and is kept only as a thin local backstop.

The **deny-list of destructive shell commands** in `security.py` (fork bomb, `curl|sh`, `mkfs`/`dd`,
`rm -rf /`, recursive `chmod`) is **retained unchanged** — it protects the local machine from an
agent, is orthogonal to GitHub, and has no repo-settings equivalent.

### 2. GitHub MCP server is the model's single access boundary, gated per agent role

Register the GitHub MCP server (remote or local) via `.mcp.json`; the token comes from an env var,
never committed. Model-facing GitHub work (read PR/issue/Actions state, comment, review, open PRs)
goes through `mcp__github__*` tools instead of scattered `gh`/`git` Bash. Access is scoped **per
role** via the agent `tools:` frontmatter and `settings.json` permissions:

- read-only critics (`reviewer`, `security-engineer`) get only read tools (`get_pull_request`,
  `…_comments`, `get_workflow_run`…), never `merge`/`push`;
- a single narrow "GitHub boundary" role holds any write tools; most roles get **no** GitHub tools.

This replaces "arbitrary Bash that can do anything" with an explicit, audited whitelist of named
operations per role — directly shrinking the number of GitHub contact points. `audit_log.py`
(matcher `*`) already records MCP tool calls, so observability is preserved.

### 3. PR watcher → Claude scheduled agent + MCP (with a restricted tool-set)

Replace the Python `pr_watch.py` loop + `scheduled.yml` cron with a **Claude scheduled cloud agent**
that wakes on cron, reads PR state through GitHub MCP, and responds. The current code's hard
invariants (**never merge, never force-push** — guaranteed by there being no such command builder)
are re-established at the **access layer**: the cron agent is granted only read + comment MCP tools,
not merge/push. This is the 3+4 combination — the safety property moves from "guaranteed by code" to
"guaranteed by tool-allowlist".

Trade-off accepted: less determinism and a per-run token cost, in exchange for far less code to
maintain and a context-aware responder. `pr_watch.py` + `dev/pr_watch.py` + `dev/run_scheduled.py`'s
PR path are deprecated once the cron agent is proven.

### 4. What stays on `gh`/`git` CLI (does not move to MCP)

MCP tools are **model-invocable only** — deterministic Python cannot call them, and the GitHub MCP
server does **not** push local commits. So these stay on CLI, by design:

- `release.py` (`git log`/`describe` to compute the semver bump), `spine_e2e.py` (`git` fixtures) —
  pure deterministic seams, already injected + tested.
- `connectors.py` (`gh run list`) — may instead be read by the cron agent via MCP (part 3); the
  Python seam stays as the non-agent fallback.
- All `git` worktree operations in the `develop` flow — git CLI is irreducible here.

## Alternatives considered

- **Full migration — everything through MCP:** rejected. Python library code cannot invoke MCP
  tools, and MCP cannot `git push` local commits or fully manage rulesets. "GitHub only through MCP"
  is not achievable for the code layer; pretending otherwise would mean rewriting deterministic seams
  to delegate to a model via `Task` — slower, costlier, and less testable.
- **Keep all local hooks (status quo):** rejected. `commit_gate` now duplicates the server gate, and
  the scattered `gh`/`git` surface gives no per-role access control — the thing the user explicitly
  wants.
- **MCP read-only, all writes on CLI:** kept for the **code layer** (part 4), but for the **model
  layer** writes go through MCP under a per-role allowlist (parts 2–3) — that is what delivers the
  "fewer, audited contact points" goal. A blanket read-only MCP would not.
- **Rewrite `commit_gate` as an MCP-aware PreToolUse hook** (matcher `mcp__github__.*`): deferred.
  It would re-add a local gate over MCP writes, but the server ruleset already guarantees the
  invariant for `master`; not worth the new structured-input parser now. Revisit if non-`master`
  branches need a local gate.

## Consequences

- Fewer GitHub contact points: model access funnels through named MCP tools with per-role scope;
  `commit_gate` is gone; the PR-watcher Python path is deprecated.
- Gating becomes **server-authoritative** — feedback moves from pre-push (local) to post-push (CI),
  accepted because the ruleset blocks any red merge to `master`.
- New runtime dependency: the GitHub MCP endpoint + a token/OAuth with correct scopes; a new failure
  mode if it is unavailable (degrade to CLI).
- The local machine deny-list (`security.py`) and the deterministic git seams (`release`,
  `spine_e2e`) are explicitly **out of scope** and unchanged.
- Touches several prior ADRs — recorded here rather than silently editing them: supersedes the
  `commit_gate` half of **0019**, refines the PR-watcher **0044/0045**, and the GitHub side of
  **0021**. Their indexes get a "refined by 0051" note when this is implemented.

## Implementation plan (staged — none applied yet)

1. **MCP boundary.** Add `.mcp.json` (scope per the user's choice) with `Authorization: Bearer
   ${GITHUB_TOKEN}`; pick remote+OAuth or PAT. Verify the server connects and tools list.
2. **Per-role access.** Define the GitHub tool-allowlist per agent role (`tools:` frontmatter) and a
   `settings.json` permission policy; default most roles to **no** GitHub tools.
3. **Drop `commit_gate`.** Remove the hook from `hooks.json` + delete `commit_gate.py` and its tests;
   trim the git-specific backstop in `security.py` only if desired (keep the deny-list). Update
   ADR 0019's index note, `docs/architecture/guardrails.md`, and the CHANGELOG.
4. **Cron PR-watcher.** Stand up a Claude scheduled agent with read+comment GitHub MCP tools;
   prove it against a live PR; then deprecate `pr_watch.py` / the `scheduled.yml` PR path.
5. **Docs.** Update `docs/architecture/extensions.md` (PR-watcher → cron+MCP), `guardrails.md`
   (gating now server-side), `configuration.md` (MCP + token), and `CLAUDE.md` (L4 / extensions).

Each step is its own gated unit of work (validate + pytest + CHANGELOG), per the constitution.
</content>
