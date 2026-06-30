# 0051 — GitHub: server-side gating + an MCP-only write boundary (trusted-repo PR watcher)

Status: Accepted — **plan**; implementation staged (no code changed yet). Hardened over **three**
three-lens reviews (MCP-capability + ADR-consistency + adversarial-security + feasibility). Chooses
**MCP-only for GitHub writes** (the model layer), with the PR watcher scoped to **trusted repos**.
Supersedes the `commit_gate`/test-gate portion of 0019; refines 0044 / 0045 (PR watcher) and the
GitHub side of 0021. The `security.py` destructive-command deny-list of 0019 is **unaffected**.

## Context

GitHub is reached from many places, with control split between the local plugin and (until recently)
nothing on the server. Three things changed the trade-off. **(1) Server-side protection:** a `master`
ruleset (CI-green + PR + no force-push/deletion + linear history), and Actions now **require approval
for all external contributors** (`all_external_contributors`, set on this repo). **(2) MCP
capability:** the GitHub MCP server commits server-side (`push_files`, Contents API) and updates a PR
branch (`update_pull_request_branch`), so the watcher needs **no `git push`** (only a true 3-way
conflict is local-git, and it is avoided). **(3) Trust model:** the watcher's security burden comes
from treating a review comment / PR as attacker-controlled. Scoping it to **trusted repos** lowers the
*likelihood* of a hostile trigger — but, as the third review established, **does not lower the
required strength of the barriers**: a trusted account can be compromised, and a trusted author's
*branch content* is still attacker-influenceable. So trust narrows *who can trigger*; the barriers
stay at full, tested strength regardless.

## Decision

### 1. Server-side gating is the merge source of truth; drop `commit_gate`

`ci.yml` + the `master` ruleset are authoritative **for merge**. `commit_gate.py` is **removed** (it
duplicated the server gate and, as a `Bash` hook, never fired on subprocess pushes). The git-specific
half of `security.py` is redundant with the ruleset (thin backstop). The **destructive-command
deny-list** is **retained unchanged** (local-machine protection).

### 2. GitHub MCP is the model's only GitHub-write surface, gated per role, deny-by-default

The MCP server config **ships with the plugin** — a committed, plugin-scoped declaration (plugin
`.mcp.json` or `mcpServers` in `.claude-plugin/plugin.json`) of the **remote** server. **Only the
non-secret declaration is committed**; the token is resolved locally (env var / OAuth), never
committed — a Tier-0 check asserts no literal secret in the config. *("MCP-only" = all GitHub
**writes** go through MCP; the fixer's working-copy **read** is local git — part 4.)* Plugin-shipped
MCP tools are named `mcp__plugin_<plugin>_<server>__<tool>`; the allowlists/matchers below use the
real, pinned ids (finalized after the step-1 spike).

Access is **deny-by-default, per role** (`tools:` frontmatter / `settings.json`, statically
inspectable): most roles get **no** GitHub tools; a Tier-0 check asserts each role's set is **exactly**
its expected allowlist (incl. the **default/un-roled interactive session** — not an escape hatch); the
server version is pinned.

### 3. PR watcher → full-MCP, privilege-separated, trusted-repo-scoped

**Trust precondition — narrows the trigger, not the barriers.** Auto-fix runs only on trusted repos
(private with limited access — documented; or public with `all_external_contributors`). A
deterministic author gate in `pr_triage.py` enforces it in code, and it **fails closed**: it calls the
**repo collaborator-permission endpoint** (`GET /repos/{o}/{r}/collaborators/{user}/permission`,
needs `metadata:read`) and treats a thread as actionable only if the author's permission is **≥
write**; **any** non-200 / timeout / rate-limit / unknown ⇒ author treated as **untrusted, thread
skipped** (so an attacker cannot induce a rate-limit to fail the gate open). Positive memberships may
be cached briefly; a cache miss never promotes to trusted. Same-repo-only (0045) is retained;
bot/app authors that are not the watcher's own bot are treated as untrusted. Fail-closed + the write
floor are **Tier-0-tested invariants**, not implementation details.

**Branch content stays untrusted even from a trusted author.** Commit authorship is forgeable and a
trusted author can carry a stranger's commits, so the *files and commit messages* the fixer reads are
still attacker-influenceable. The input-side defences therefore stay at **full strength** (not
downgraded): the fixer runs **no-Bash / no-network**, with its untrusted-input prompt frame (0045).

**Control-flow (resolved, fail-closed).** Python cannot invoke MCP, so the headless **agent
orchestrates** the MCP calls and a **PreToolUse hook is the deterministic gate** on every
`mcp__github__*` write. Because Claude Code hooks **fail open by default** (feasibility), this hook is
an **explicit fail-closed exception**: it blocks (deny / exit 2) on any validation failure **and on
its own error/timeout**, and a **`settings.json` permission rule is the backstop** (a crashed hook
still can't widen the tool set). The matcher is the **prefix `mcp__github__*` with default-deny** — any
GitHub MCP write tool the hook doesn't explicitly recognise-and-validate is **blocked** (so a server
version bump exposing `create_or_update_file`/`merge_pull_request`/`delete_ref`/… cannot slip through
unvalidated). The hook reads its authoritative state from a channel **the agent cannot write** (a
launcher-set env var / a path outside every agent-writable root), or re-fetches targets from GitHub;
the **executor role has no Write/Edit**.

**Three roles behind a deterministic frame** (`pr_triage.py`, tested Python, owns every invariant):

- **Triage (MCP read).** Reads the PR under processing; read-tool args (`number`/`owner`/`repo`) are
  **frame-pinned** (post-validated), since the token doesn't pin reads to one PR. Proposes
  classifications; the **frame** computes the actionable set and the resolvable thread-id set (C2).
- **Fixer (sandbox, from 0044/0045).** No-MCP / no-Bash / no-network, Read/Write/Edit/Grep/Glob over a
  local checkout. **Config isolation:** the fixer runs with a **project root outside the checkout** so
  the checkout's `CLAUDE.md`, `.claude/settings.json`, `.claude/` hooks/agents, and skills are **never
  auto-loaded** (`--strict-mcp-config` alone covers only `.mcp.json`); the checkout is a read-only data
  path. Tier-0 asserts these surfaces don't load. Every frame git op on the checkout sets
  **`core.hooksPath=/dev/null`** (0045 — hostile tracked hooks).
- **Diff-guard (frame-computed, default-deny, deny-wins).** The **frame** — never the comment or the
  agent — computes the allowed set from the PR's **pre-existing changed-file set** intersected with a
  **static** safe-dir policy, and applies a **hard denylist that beats any allow**: `.github/`, git
  hooks, `CODEOWNERS`, lockfiles, `conftest.py`, build/CI files (`Makefile`/`Dockerfile`/`package.json`/
  `pyproject.toml`/`tox.ini`/…), `.mcp.json`, `.claude/`, `.claude-plugin/`, `plugin.json`, `.git/`.
  A staged diff touching anything outside the allow-set or inside the deny-set is **rejected**; file
  count is capped. Tier-0-and-unit-tested unconditionally (full strength regardless of trust).
- **Executor (narrow MCP write).** Allowlist is **exactly** `{push_files, update_pull_request_branch,
  add_comment, resolve_thread}` (Tier-0-asserted; matcher default-deny above). **Every field of every
  write tool** is a frame-supplied validated token, never model prose (C1 + Sec-1): reply bodies are
  closed templates (`fixed` → `"Addressed in {sha}."`, `sha` `^[0-9a-f]{7,40}$`; else canned); the
  `push_files` **commit message** is a closed template (no `thread.path`); `owner`/`repo`/`branch` are
  **frame-authoritative** (validated `headRefName`), never agent-chosen (Sec-4). The fail-closed hook
  re-checks all of it. The fix commits via `push_files` (no `git push`); a behind branch updates via
  `update_pull_request_branch`; a **true 3-way conflict** is not resolved — the frame posts the
  idempotent `CONFLICT_NOTICE` once and stops.

**MCP config isolation (Sec-3A, CRITICAL).** The executor runs with **`--strict-mcp-config` +
`--mcp-config <trusted absolute path>`**, so a `.mcp.json` in the target checkout is **never** loaded
(no token redirect/exfil); the server `url` is re-verified at runtime.

Every MCP write emits a **forced** `diagnostics.emit(force=True)` recording the **triggering author**
(insider/compromise abuse is auditable) — the mandated outward-write audit of 0044 §7, not the
off-by-default usage log (P1-2 / 0039).

### 4. What stays on local git (NOT a GitHub write)

`push_files` replaces `git push`, so **no GitHub write uses local git**. Local VCS remains:
`release.py` (`git log`/`describe`), `spine_e2e.py` (fixture repos), `develop` worktrees, and the
fixer's working-copy checkout (a local *read*; all writes MCP-only). Reads occur on two paths — MCP
(triage) and REST (`pr_triage.py` membership) — both reads, consistent with a write-only MCP boundary.

## Security model

Normally a review comment / PR is attacker-controlled. **Trust precondition (primary, fail-closed)**
lowers the *likelihood* of a hostile trigger. But the barriers below are **NOT lighter** — they stay
at full, tested strength, because (a) a trusted account can be compromised, leaving the barriers as
the *only* control, and (b) branch content is attacker-influenceable even from a trusted author. Trust
reduces probability; it never reduces barrier strength. The claim is precise: the watcher never
processes attacker-controlled **instructions/identities** (gated) — branch **content** is still
treated as untrusted by the sandbox.

| Risk | Barrier (full strength, tested) |
| --- | --- |
| untrusted/compromised author triggers a run | author gate **fails closed**, permission ≥ write |
| prose/exfil via any write field (C1/Sec-1) | closed templates on **every** field; fail-closed PreToolUse hook |
| resolve an unintended thread (C2) | Python-authoritative ids; hook-checked; re-fetched |
| CI-executing file slips in (Sec-2) | **frame-computed** default-deny allowlist + **deny-wins** sensitive set |
| token redirect via checked-out `.mcp.json` (Sec-3A) | `--strict-mcp-config` + trusted absolute path |
| instruction injection via checked-out `CLAUDE.md`/`.claude/` | fixer project-root **outside** the checkout |
| re-arm via edited config files (Sec-3B) | config paths in the deny-wins set |
| write to `gh-pages`/release branch (Sec-4) | frame-authoritative `owner`/`repo`/`branch` |
| hostile tracked git hooks (Sec-6) | `core.hooksPath=/dev/null` on every frame git op |
| unmatched future write tool (hook bypass) | matcher `mcp__github__*` default-deny + Tier-0 exact-allowlist |
| crashed hook lets a write through | hook fails **closed** + permission-rule backstop |
| push to `master` | the ruleset — agent-independent |

**Token-leak (Sec-5) and token-custody are the risks trust does NOT cover** — credential exposure,
not injection (see Token & auth).

## Token & auth

- **Interactive layer:** OAuth (browser login, nothing stored).
- **Headless cron watcher:** OAuth can't run headless and its refresh token is itself long-lived, so
  OAuth does not solve token-leak. The real fix is a **GitHub App installation token** (1-hour,
  auto-rotating), but the **GitHub MCP server doesn't support App auth yet** (issue #696). So the MCP
  path uses a **fine-grained PAT** (single repo, `pull_requests:write`+`contents:write`+`metadata:read`,
  stable bot identity). Two residual risks, both *managed not eliminated* on the MCP path:
  - **leak:** short max-lifetime + automated rotation + **secrets-manager (not plaintext env)** at
    rest + a revoke runbook; honest worst case = full `contents:write` on **every branch** of that one
    repo (bounded by single-repo scope, no `admin`/`workflows`).
  - **custody:** the PAT is presented to **`api.githubcopilot.com` on every MCP call** — a write-capable
    token transits a third-party endpoint (its logs / TLS termination). Pin the host + verify URL/TLS
    at runtime. **Alternative B removes this hop entirely** (token only ever reaches `api.github.com`)
    and can use an App token today — the custody + leak rationale for preferring B where the goal
    allows.

## Evals & determinism

`triage`/`executor` are agent roles → they ship `agents/evals/<role>.evals.json` + **Tier-2** (N≥5
LLM-judge), gated like the six existing roles; roles carry **no Tier-1** and add **nothing** to the
on-listing budget. All safety-critical logic — fail-closed author gate (+ write floor),
actionable/resolvable sets, frame-computed default-deny diff-guard, closed templates,
frame-authoritative targets, `core.hooksPath=/dev/null`, checkout config-isolation — stays **tested
Python** in `pr_triage.py` + the **fail-closed** PreToolUse hook; the agent only *selects*, the
frame/hook *enforce* (P1-3 / P2-7).

## Alternatives considered

- **(B) Deterministic Python commits via the GitHub Contents REST API** (not MCP): **strictly safer on
  the axes the three reviews kept hitting** — C1/C2 are *natively* enforced (Python writes the exact
  validated bytes; no agent-authored args, no fail-open-hook dependency), no MCP token-custody hop, and
  it can use an **auto-rotating App token today** (eliminates Sec-5). Deterministic, unit-tested,
  non-agent (no Tier-2). **Not chosen** because the stated goal is GitHub-via-MCP and the watcher is
  scoped to trusted repos; recorded as the **preferred fallback** and the **required** path for
  untrusted/public repos (where the trust precondition cannot hold). The path-A hardening above exists
  precisely because A's safety is a *product* of many controls where B's is intrinsic.
- **Naive single agent / Hybrid / migrate the code layer:** rejected/​fallback as before (privilege
  confusion; MCP-unavailable pins to the hardened `pr_watch.py`; Python can't call MCP for the seams).

## Consequences

- GitHub **writes** are MCP-only via four tools, deny-by-default + fail-closed hook, every write
  force-audited with the triggering author; `commit_gate` gone; the watcher's `git push`/`git merge`
  removed.
- Watcher is **trusted-repo-only** — explicitly **not** safe for public/OSS repos with PRs from
  strangers (there: Alternative B, or no auto-fix). Deliberate scope limit.
- Safety on path A is a **product of ~10 tested controls** (fail-closed gate, fail-closed hook,
  default-deny matcher, frame-computed diff-guard, checkout isolation, strict-MCP-config,
  frame-authoritative targets, closed templates, write floor, hooks-off). B would make most intrinsic;
  A's choice is accepted with that cost stated.
- New dependencies/failure modes: the MCP endpoint (token-custody) + PAT (rotation/secrets-manager);
  API rate limits (the author gate fails closed under them); reliance on the collaborator-permission
  API.
- Touches prior ADRs (recorded): supersedes `commit_gate`/test-gate of **0019** (and the write-arg hook
  is a documented fail-closed exception to 0019's fail-open default); refines **0044/0045** (trust gate
  + MCP write path) and the GitHub side of **0021**.

## Implementation plan (staged — none applied yet)

1. **Verify the plugin-MCP mechanism (spike).** Confirm a plugin can ship MCP config, that token
   interpolation keeps it uncommitted, and **pin the real `mcp__plugin_…__…` tool ids**; confirm the
   PreToolUse hook can match `mcp__github__*`, read `tool_input`, and block — and how to make it
   fail-closed (+ the permission-rule backstop). Don't build on unverified mechanisms.
2. **MCP boundary + per-role allowlist.** Ship the no-secret plugin config; Tier-0 checks
   (no-secret-in-config; per-role allowlist is exactly the expected set incl. the un-roled session;
   matcher is default-deny `mcp__github__*`).
3. **Drop `commit_gate`.** Remove hook + `commit_gate.py` + tests; deprecate `test_gate.skip`; update
   0019's index note, `guardrails.md`, CHANGELOG.
4. **Deterministic frame + fail-closed hook (the safety core, tested Python).** `pr_triage.py`:
   fail-closed author gate (collaborator-permission endpoint, ≥ write, error⇒untrusted),
   actionable/resolvable sets, **frame-computed** default-deny diff-guard (pre-existing changed files ∩
   static policy, deny-wins set, file cap), closed templates incl. commit message, frame-authoritative
   targets, `core.hooksPath=/dev/null`, checkout config-isolation (project-root outside the checkout).
   The PreToolUse `mcp__github__*` write-arg hook: fail-closed, authoritative state from a
   non-agent-writable channel, executor role has no Write/Edit. Unit-test every error path.
5. **Agent roles + wiring.** Add `triage`/`executor` contracts + Tier-2; executor runs with
   `--strict-mcp-config`/trusted `--mcp-config`; provision the PAT (secrets-manager, rotation,
   auto-merge verified off **per run**, host/TLS pinned). Migrate/rename `pr_watcher.*` + schema; retire
   `dev/run_scheduled.py`'s PR path + the `scheduled.yml` watcher job. Prove on a throwaway PR (0045).
6. **Docs (incl. doc-sync).** Update `meta-core.md` (new `pr_triage.py` row + revised `pr_watch.py`
   row — `validate.py` doc-sync gates this), the **ADR index** entry, `extensions.md`, `guardrails.md`,
   `configuration.md` (MCP config, PAT, rotation, the fail-closed author gate), `CLAUDE.md`, and the
   trusted-repo policy in `SECURITY.md`.

Each step is its own gated unit of work (validate + pytest + CHANGELOG).

## Open questions (operational)

- PAT rotation cadence + secrets-manager choice; revoke runbook.
- Rate-limit / backoff for hourly polling (distinct from the gate's fail-closed-on-rate-limit).
- Adopt Alternative B if scope widens beyond trusted repos, or once the MCP server supports GitHub App
  auth (then the MCP path can drop the long-lived PAT and the custody hop too).
</content>
