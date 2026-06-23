# 0019 — L4 guardrails: deterministic hooks (security, test-gate, logging, budgets)

Status: Accepted

## Context

L0–L3 are built; L4 (guardrails / observability) is the last layer. CLAUDE.md scopes it as
"hooks (security, test-gate, logging, budgets)"; roadmap Stage 7 frames it more broadly as
"Guardrails, observability, **scheduling**." The session-start hook (ADR 0018) established the
`plugin/hooks/` pattern — `hooks.json` + thin Python scripts that reuse a tested `lib/` module.
L4 generalises that pattern to runtime guardrails on tool use.

## Decision

- **Scope = the four guardrail hooks** in CLAUDE.md (security, test-gate, logging, budgets).
  **Scheduling is out of L4** — it is headless cadence, not a guardrail; deferred to a later
  Stage-7 increment. (This reconciles the scope drift: CLAUDE.md + `overview.md` already list the
  four hooks; the roadmap's "scheduling" is the broader superset, recorded as a follow-on.)
- **Deterministic core in `lib/agentic_forge/guardrails.py`** (tested, aim 100%); the hook
  scripts under `plugin/hooks/scripts/` only parse the hook JSON (stdin) and call the lib — the
  same split as `vault.py` ↔ `session_start.py`. New `hooks.json` entries register them.
- **security** — a `PreToolUse` hook: **block (exit 2)** unambiguously-dangerous `Bash`
  commands (`rm -rf` of `/` or `$HOME`, fork bombs, `curl|sh`, `mkfs`/`dd` to a device,
  `chmod -R 777 /`, force-push to a protected branch). A conservative **deny-list** — false
  positives cause friction, so it blocks only clear hazards and otherwise allows. (Path/worktree
  isolation stays the worktree pattern's job; the hook does **not** block out-of-cwd writes,
  which would fight legitimate worktrees.)
- **test-gate** — a `PreToolUse` hook on `git commit` / `git push`: run a **fast** gate and block
  on failure — `dev/validate.py` if the repo has it, else the detected stack's lint/typecheck
  (`stacks.primary(cwd).toolchain`, reusing by-stack). Skippable via an env flag for emergencies.
- **logging** — a `PostToolUse` hook: append a redacted JSONL audit line (tool, brief, secrets
  redacted) under `${CLAUDE_PROJECT_DIR}/.agentic-forge/`. **Never blocks** (pure observability).
- **budgets** — a `PreToolUse` hook on the `Task` (subagent) tool: count spawns per session
  (state in a session-scoped file keyed by `session_id`), **warn** over a soft cap and **block**
  over a hard cap. Configurable.
- **Fail-open by default.** A guardrail bug must never break a session: every hook catches its
  own errors and exits 0 (allow) — *except* the security and test-gate blocks, where exit 2 is
  the intended behaviour. Each hook is unit-tested on **both** allow and block paths.

## Alternatives considered

- **Guardrails as rules (CLAUDE.md text), not hooks:** rejected for the enforceable ones —
  instructions are advisory; only a hook deterministically blocks. (Soft guidance stays as
  skill/role text; the hard guarantees are hooks.)
- **Run the full test suite in the test-gate hook:** rejected — too slow for a PreToolUse hook;
  use the fast Tier-0 / lint gate, scoped to commit/push only.
- **LLM-judged security:** rejected — blocking must be deterministic and fast; a tested,
  conservative deny-list classifier instead.
- **Block out-of-project writes in the security hook:** rejected — it would block legitimate git
  worktrees (which can live outside cwd); isolation is the worktree pattern's responsibility.
- **Include scheduling in L4:** rejected — not a guardrail; keeps L4 = the four hooks per
  CLAUDE.md, scheduling deferred.

## Consequences

- New `guardrails.py` + four hook scripts + `hooks.json` PreToolUse/PostToolUse entries; the
  plugin gains runtime enforcement on top of L3's session-start injection.
- test-gate + budgets reuse `stacks` and session state; logging writes under the project dir.
- Friction risk (the roadmap's stated risk) is mitigated: conservative classifiers, fail-open on
  hook errors, allow+block tests, a skippable test-gate.
- Completes L4; scheduling / observability dashboards remain a documented Stage-7 follow-on.

## Exit criteria

- `guardrails.py` unit-tested on allow + block, coverage ≥ 80% (aim 100%); each hook script
  tested (block → exit 2, allow → exit 0, internal error → fail open exit 0).
- `hooks.json` valid; Tier-0 + full gate green; independent adversarial review clean.
- Docs: this ADR, `docs/architecture/guardrails.md`, and overview / roadmap / CLAUDE / meta-core
  updated; CHANGELOG entries per step.
