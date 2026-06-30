# 0051 — GitHub: server-side gating + an MCP-only write boundary (trusted-repo PR watcher)

Status: Accepted — **plan**; implementation staged (no code changed yet). Hardened over **two
three-lens reviews** (MCP-capability + ADR-consistency + adversarial-security). Chooses **MCP-only
for GitHub writes** (the model layer), with the PR watcher scoped to **trusted repos** so it never
processes attacker-controlled input. Supersedes the `commit_gate`/test-gate portion of 0019; refines
0044 / 0045 (PR watcher) and the GitHub side of 0021. The `security.py` destructive-command deny-list
of 0019 is **unaffected**.

## Context

GitHub is reached from many places, with control split between the local plugin and (until recently)
nothing on the server: local guardrail hooks (`commit_gate.py`, `security.py`), deterministic library
seams that shell out to `gh`/`git` (`connectors.py`, `pr_watch.py`, `release.py`, `spine_e2e.py`,
dev CLIs), and ad-hoc `Bash`.

Three things changed the trade-off. **(1) Server-side protection:** a `master` ruleset now requires
the `Tier 0 (static gate)` check + a PR before merge, forbids force-push/deletion, enforces linear
history; and this repo's Actions now **require approval for all external contributors**
(`all_external_contributors`), so a stranger's PR cannot run CI/automation without an admin first
trusting them. **(2) GitHub MCP capability:** the server can commit files server-side
(`push_files`/`create_or_update_file`, Contents API) and update a PR branch
(`update_pull_request_branch`), so a PR-fix workflow needs **no `git push`** — only a true 3-way
merge conflict is irreducibly local-git. **(3) Trust model:** the watcher's whole security burden
comes from treating a review comment / PR branch as attacker-controlled. If the watcher only ever
runs on **trusted repos** (private, or public-with-`all_external_contributors`, plus a
trusted-author gate), that input is no longer hostile — which removes the *root cause* of the
adversarial findings rather than fighting each symptom.

## Decision

### 1. Server-side gating is the source of truth; drop `commit_gate`

`ci.yml` + the `master` ruleset are authoritative. `commit_gate.py` is **removed** (it duplicated the
server gate and, being a `Bash` hook, never fired on the watcher's subprocess pushes). The
git-specific half of `security.py` is redundant with the ruleset (kept as a thin backstop). The
**destructive-command deny-list** is **retained unchanged** (local-machine protection, orthogonal to
GitHub).

### 2. GitHub MCP is the model's only GitHub-write surface, gated per role, deny-by-default

The MCP server config **ships with the plugin** — a committed, plugin-scoped declaration (a plugin
`.mcp.json` or the `mcpServers` field of `.claude-plugin/plugin.json`) of the **remote** server
(`https://api.githubcopilot.com/mcp/`). **Only the non-secret server declaration is committed**; the
token/OAuth is resolved locally (env var / OAuth), never committed — a Tier-0 check asserts the
committed config carries no literal secret. *("MCP-only" means all GitHub **writes** go through MCP;
a local-checkout **read** for the fixer's working copy is still local git — see part 4.)*

Access is **deny-by-default, per role**: most roles get **no** GitHub tools; read-only critics get
specific read tools; a Tier-0 check asserts each role's tool set is **exactly** an expected allowlist
(a blocklist would silently re-arm on a server version bump — H3); the MCP server version is pinned.
The **default/un-roled interactive session** is covered by the same allowlist gate (it is not an
escape hatch).

### 3. PR watcher → full-MCP, privilege-separated, **trusted-repo-scoped**

**Trust precondition (the primary control).** Auto-fix runs **only** on trusted repos: private repos
with limited access (documented requirement), or public repos with `all_external_contributors`
approval (this repo). A **deterministic author gate in `pr_triage.py`** enforces it in code: a thread
is actionable only if its author is a trusted collaborator (membership checked via the GitHub API);
PRs are same-repo-only (0045) and may additionally require the PR author to be trusted. So the
watcher **never processes attacker-controlled input** — which is what neutralises the adversarial
findings (see Security model). The barriers below are then **defence-in-depth** (against accident or a
compromised trusted account), not the sole guard.

**Control-flow (the crux, resolved honestly).** Python cannot invoke MCP tools — they are
model-invocable. So the **headless agent session orchestrates** (it issues the MCP calls), and a
**deterministic PreToolUse hook enforces the write-argument invariants** — the same mechanism as
`security.py` on Bash, with a matcher on the `mcp__github__*` write tools. The hook reads the
frame's authoritative state and **blocks (exit 2)** any write whose arguments fall outside it. This
is what makes C1/C2 machine-enforced rather than "trust the model": the agent *proposes* the call;
the hook *is* the gate.

**Three roles behind a deterministic frame** (`pr_triage.py`, tested Python, owns every invariant):

- **Triage (MCP read).** Reads the PR under processing. Read-tool args (`number`, `owner`, `repo`)
  are **frame-pinned** (post-validated), since the repo-scoped token does not by itself pin reads to
  one PR (cross-cutting finding). Proposes classifications; the **frame**, not the model, computes the
  actionable set and the resolvable thread-id set (C2).
- **Fixer (sandbox, from 0044/0045).** No MCP, no Bash, no network — Read/Write/Edit/Grep/Glob over a
  local checkout. The frame's local git ops on that checkout (`checkout`/`add`/`commit`/`diff`) all
  set **`core.hooksPath=/dev/null`** so hostile *tracked* hooks in the branch cannot run (0045,
  restated for the new path — Sec-6). The frame then runs a **default-deny diff-guard**: an
  **allowlist** of permitted path globs (the fix's scoped source dirs); everything else — `.github/`,
  hooks, `CODEOWNERS`, lockfiles, `conftest.py`, build/CI files (`Makefile`, `Dockerfile`,
  `package.json`, `pyproject.toml`, `.mcp.json`, `.claude-plugin/`, `plugin.json`, `.claude/`,
  `.git/`) — is **rejected** (Sec-2/Sec-3B). Enumerating "sensitive" globs is unwinnable; default-deny
  is the only safe shape.
- **Executor (narrow MCP write).** Allowlist is **exactly** `{push_files, update_pull_request_branch,
  add_comment, resolve_thread}` (Tier-0-asserted). **Every field of every write tool** is a
  frame-supplied validated token, never model prose (C1 + Sec-1): reply bodies are closed templates
  (`fixed` → `"Addressed in {sha}."`, `sha` matched `^[0-9a-f]{7,40}$`; `rejected`/`conflict` →
  canned); the `push_files` **commit message** is likewise a closed template (no `thread.path`
  interpolation); `owner`/`repo`/`branch` are **frame-authoritative** (the validated `headRefName`),
  never agent-chosen, so a write cannot target `gh-pages`/release branches (Sec-4). The PreToolUse
  hook re-checks all of this. The fix commits via `push_files` (no `git push`); a behind branch
  updates via `update_pull_request_branch`. A **true 3-way conflict** is not resolved (no server-side
  merge) — the frame posts the idempotent `CONFLICT_NOTICE` once and stops.

**MCP config isolation (Sec-3A, CRITICAL).** The executor runs with **`--strict-mcp-config` and an
explicit `--mcp-config <trusted absolute path>`** pointing at the plugin-install config, so a
`.mcp.json` present in the *target PR checkout* is **never** loaded — a malicious branch cannot
redirect the MCP `url` and exfiltrate the token. The server `url` is re-verified at runtime.

Invariants (**never merge / never force-push / same-repo / idempotent / audited**) hold via: the
trust gate (primary), the deny-by-default allowlist + PreToolUse arg-hook, frame-authoritative
targets, the default-deny diff-guard, strict-MCP-config, and the server ruleset. Every MCP write
emits a **forced** `diagnostics.emit(force=True)` — the mandated outward-write audit of 0044 §7, not
the off-by-default usage log (P1-2 / 0039).

### 4. What stays on local git (NOT a GitHub write)

`push_files` replaces `git push`, so **no GitHub write uses local git**. What remains is local VCS:
`release.py` (`git log`/`describe` — local history), `spine_e2e.py` (local fixture repos),
`develop` worktrees, and the fixer's **working-copy checkout** (a local *read* from the remote;
all writes stay MCP-only). The checkout-free MCP `get_file_contents` variant is the fallback if a
lighter fixer ever suffices.

## Security model

Threat: normally a review comment / PR branch is attacker-controlled. **Primary control: the trust
precondition** (part 3) — the watcher runs only where comment authors and branch authors are trusted
collaborators, enforced by the `pr_triage.py` author gate + `all_external_contributors` + same-repo.
This removes the active attacker, so the adversarial findings (C1, C2, Sec-1/2/3/4/6) lose their
root cause. The barriers below are **defence-in-depth** for accident or a compromised trusted account:

| Residual risk | Barrier (defence-in-depth) |
| --- | --- |
| prose/exfil via any write field (C1/Sec-1) | closed templates on **every** field; PreToolUse arg-hook |
| resolve an unintended thread (C2) | Python-authoritative ids, hook-checked, re-fetched |
| CI-executing file slips in (Sec-2) | **default-deny** diff-guard (allowlist of source globs) |
| token redirect via checked-out `.mcp.json` (Sec-3A) | `--strict-mcp-config` + trusted absolute config path |
| re-arm via edited config files (Sec-3B) | config paths in the default-deny guard |
| write to `gh-pages`/release branch (Sec-4) | frame-authoritative `owner`/`repo`/`branch` |
| hostile tracked git hooks (Sec-6) | `core.hooksPath=/dev/null` on every frame git op |
| push to `master` | the ruleset (API or git) — agent-independent |

**Token-leak (Sec-5) is the one risk the trust model does NOT cover** — it is credential exposure,
not injection (see Token & auth). It is *managed*, not eliminated, on the MCP path.

## Token & auth

- **Interactive layer:** OAuth (browser login, nothing stored).
- **Headless cron watcher:** OAuth cannot run headless, and a stored OAuth **refresh token is itself a
  long-lived secret** — so OAuth does not solve token-leak. The real fix is a **GitHub App
  installation token** (1-hour, auto-rotating), but the **GitHub MCP server does not support App auth
  yet** (issue #696). So on the MCP path the watcher uses a **fine-grained PAT** (single repo,
  `pull_requests:write`+`contents:write`, stable bot identity for the `author≠bot` skip), and
  token-leak is *managed*: short max-lifetime + automated rotation, **secrets-manager (not plaintext
  env) at rest**, a documented revoke runbook, and the honest worst case — a leaked PAT = full
  `contents:write` on **every branch** of that one repo (not "one PR"), bounded by single-repo scope +
  no `admin`/`workflows`. (Alternative B below would instead use an App token and eliminate this.)

## Evals & determinism

`triage`/`executor` are agent roles → they ship `agents/evals/<role>.evals.json` + **Tier-2** (N≥5
LLM-judge), gated like the six existing roles; roles carry **no Tier-1** and add **nothing** to the
on-listing budget. All safety-critical logic — author gate, actionable/resolvable sets, diff-guard,
templates, frame-authoritative targets — stays **tested Python** in `pr_triage.py` + the PreToolUse
hook; the agent only *selects*, the frame/hook *enforce* (P1-3 / P2-7).

## Alternatives considered

- **(B) Deterministic Python commits via the GitHub Contents REST API** (not MCP): **stronger on two
  axes** — C1/C2 are *natively* enforced (Python writes the exact validated bytes, no agent-authored
  args, no PreToolUse-hook needed), and it can use a **GitHub App installation token** today
  (eliminates token-leak Sec-5). It keeps the watcher deterministic, unit-tested, non-agent (no
  Tier-2). **Not chosen** because the stated goal is GitHub-via-MCP; recorded as the **preferred
  fallback** if the MCP write path's hardening proves too costly, and as the strictly-safer option for
  **untrusted/public** repos where the trust precondition cannot hold.
- **Naive single agent (read+fix+write in one principal):** rejected — privilege confusion.
- **Hybrid (MCP for session/read only; watcher stays on `gh`/`git`):** the MCP-unavailable fallback;
  pin it to the existing hardened `pr_watch.py` core, not an ad-hoc shell.
- **Migrate the deterministic code layer to MCP:** rejected — Python can't invoke MCP; local-git /
  tested seams stay (consistent with 0021's MCP-or-`gh` `PipelineSource`).

## Consequences

- GitHub **writes** are MCP-only via four named tools, deny-by-default, every write force-audited;
  `commit_gate` gone; the watcher's `git push`/`git merge` removed (`push_files`/update-branch).
- Watcher is **scoped to trusted repos** — explicitly **not** safe for public/OSS repos with PRs from
  strangers (there, use Alternative B or do not auto-fix). This is a deliberate scope limit.
- New surface to gate: two Tier-2 roles, a PreToolUse write-arg hook, a default-deny diff-guard +
  templater + author gate + allowlist check (Tier-0), a pinned MCP server + least-privilege PAT +
  strict-MCP-config, the plugin-shipped (no-secret) MCP config, and `all_external_contributors` on
  this repo (done).
- New dependencies/failure modes: the MCP endpoint + PAT (rotation/secrets-manager — Sec-5); API
  **rate limits** for hourly polling; reliance on the GitHub membership API for the author gate.
- Touches prior ADRs (recorded, not silently edited): supersedes `commit_gate`/test-gate of **0019**;
  refines **0044/0045** (adds the trust gate + MCP write path) and the GitHub side of **0021**.

## Implementation plan (staged — none applied yet)

1. **Verify the plugin-MCP mechanism (spike).** Confirm against Claude Code plugin docs that a plugin
   can ship MCP config and that `${VAR}` interpolation keeps the token uncommitted; pin the exact
   tool ids (`add_comment`/`resolve_thread`/`push_files`/`update_pull_request_branch` are
   representative — bind to the server's real names). Don't build on an unverified mechanism.
2. **MCP boundary + per-role allowlist.** Ship the no-secret plugin config; add the Tier-0 checks
   (no-secret-in-config; per-role allowlist is exactly the expected set, incl. the un-roled session).
   Confirm `validate.py` can read each role's MCP tool grant (frontmatter `tools:` / `settings.json`).
3. **Drop `commit_gate`.** Remove the hook + `commit_gate.py` + tests; deprecate the `test_gate.skip`
   setting; update ADR 0019's index note, `guardrails.md`, CHANGELOG.
4. **Deterministic frame + hook.** Build + unit-test `pr_triage.py` (author gate via the membership
   API, actionable/resolvable sets, default-deny diff-guard, closed templates incl. commit message,
   frame-authoritative targets, `core.hooksPath=/dev/null`) **and** the PreToolUse `mcp__github__*`
   write-arg hook. These are the safety-critical, tested-Python core.
5. **Agent roles + wiring.** Add `triage`/`executor` contracts + Tier-2; run the executor with
   `--strict-mcp-config`/trusted `--mcp-config`; provision the PAT (secrets-manager, rotation,
   auto-merge verified off **per run**). Migrate/rename the `pr_watcher.*` settings + schema; retire
   `dev/run_scheduled.py`'s PR path + the `scheduled.yml` watcher job as superseded. Prove on a
   throwaway PR per the 0045 runbook.
6. **Docs (incl. doc-sync).** Update `meta-core.md` (new `pr_triage.py` row + revised `pr_watch.py`
   row — **`validate.py` doc-sync gates this**), `extensions.md`, `guardrails.md`, `configuration.md`
   (MCP config, PAT, rotation, the trusted-author gate), `CLAUDE.md`, and the trusted-repo policy in
   `SECURITY.md`.

Each step is its own gated unit of work (validate + pytest + CHANGELOG).

## Open questions (operational)

- PAT rotation cadence + secrets-manager choice for the headless env; revoke runbook.
- Rate-limit / backoff strategy for hourly polling across configured repos.
- Whether to adopt Alternative B (App token, native C1/C2) if/when broader-than-trusted repos are in
  scope, or once the MCP server supports GitHub App auth (then the MCP path can drop the PAT too).
</content>
