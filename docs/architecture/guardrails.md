# Layer 4 — Guardrails (hooks)

Status: **Built** ([ADR 0019](decisions/0019-l4-guardrails.md)) — four deterministic guardrail
hooks on tool use, on top of L3's session-start hook. **Scheduling & observability shipped
separately** ([ADR 0024](decisions/0024-stage7-scheduling-observability.md),
[scheduling-observability.md](scheduling-observability.md)); this doc covers only the hooks.

The guardrails turn the project's discipline into **enforcement**: a hook deterministically
blocks (or warns) where a CLAUDE.md rule would only advise. They live under `plugin/hooks/`
(`hooks.json` + `scripts/`) as thin glue over `lib/agentic_forge/guardrails.py` (deterministic,
100% tested). Each hook **fails open** on its own error — a guardrail bug must never break a
session — except where blocking is the whole point (security, test-gate).

## The hooks

- **security** (`PreToolUse` / Bash, `security.py`) — blocks clearly-dangerous commands via a
  conservative deny-list: recursive/forced `rm` or permissive `chmod` of `/`/`~`/a system dir,
  fork bombs, a network download piped into a shell/interpreter, `mkfs`/`dd` to a device, raw-disk
  writes, a `find <root/system-dir> … -delete` (whole-tree delete), and force-push (`--force` or a
  `+refspec`) to a protected branch. Exit 2 blocks;
  everything else is allowed (false positives cause friction, so it blocks only unambiguous hazards).
  Every rule fires on the **command word** of a **quote-aware segment** (ADR 0051 for the
  network-download rule, ADR 0054 for the rest): segments split on `;`/`|`/`&`/newline *outside
  quotes*, tokens come from `shlex`, and the rule's command must be the segment's command word
  (after `sudo`/env-assignment/wrapper prefixes). So `ls /usr && rm -rf build` is not misread as
  `rm -rf /usr`, and a command that merely *quotes* a dangerous string — `git commit -m "block
  rm -rf /"`, `grep "rm -rf /" docs/`, a `python3 -c` script holding the pattern — never blocks,
  while executable payloads (`bash -c "rm -rf /"`, `$(…)`/backtick substitutions) are re-classified
  recursively and still do. The network-download check additionally requires a **bare** interpreter
  (one reading *stdin as its program*) fed from a **non-loopback** host — so `curl localhost … |
  python3 -c` (local observability) and `… | python3 -m json.tool` (data parsing) pass while
  `curl https://…/install.sh | sh` blocks. A segment `shlex` cannot tokenize (unbalanced quotes)
  degrades to the pre-0054 text checks — block-leaning, never silently passing.
- **test-gate** (`PreToolUse` / Bash, `commit_gate.py`) — on `git commit`/`git push`, runs the
  **fast** gate (`dev/validate.py` if present, else the detected stack's lint via `stacks.py`) and
  blocks on failure, so broken code isn't committed. Skippable via `AGENTIC_FORGE_SKIP_TEST_GATE`;
  fails open on an infrastructure error (missing tool, timeout).
- **budgets** (`PreToolUse` / Task, `budget.py`) — a per-session subagent counter; **warns** over
  the soft cap and **blocks** over the hard cap (`AGENTIC_FORGE_SUBAGENT_SOFT` / `_HARD`).
- **logging** (`PostToolUse`, `audit_log.py`) — appends a secret-redacted JSONL audit line to
  `<project>/.agentic-forge/audit.jsonl`. Pure observability; **never blocks**.

## Design notes

- **Deterministic, not LLM-judged** — blocking must be fast and predictable; the classifiers are
  tested deny-lists, conservative by design to avoid friction (the roadmap's stated risk).
- **Reuse** — the test-gate reuses by-stack (`stacks.py`); budgets use a session-scoped counter
  file; logging reuses the redaction in `guardrails.py`.
- **Exit-code contract** — `2` = block (reason on stderr, fed back to the model); `0` = allow (a
  non-blocking warning may still print to stderr).

## Scope: an accident-guard, not an adversarial sandbox

The security deny-list and secret redaction stop **unambiguous hazards and accidental leaks**, not
a determined adversary. Known, accepted limits:

- **Bypassable by obfuscation.** `sh -c` payloads and `$(…)`/backtick substitutions are re-classified
  recursively (ADR 0054), but a substitution whose *download output becomes the program*
  (`bash -c "$(curl …)"` — no pipe, nothing dangerous in the literal text), a wrapper flag that
  takes a separate argument (`sudo -u root rm …` — the flag's argument masks the command word),
  remote execution (`ssh host 'rm …'`), and a bare `git push --force` with no explicit target (the
  destination branch isn't knowable from the command string) are not caught. The list errs toward
  *allow* to avoid friction.
- **The test-gate runs repo-local code by design.** `commit_gate` executes the project's own
  `dev/validate.py` (or the stack lint) from the session `cwd`; the trust boundary is Claude
  Code's `cwd`, not the hook. Don't point a session at an untrusted repo and then commit.
- **Redaction covers common token shapes** (`sk-…`/`sk-ant-…`, `gh*_`/`github_pat_`/`glpat-`,
  AWS/Google/Slack keys, JWTs, `user:pass@` URLs, Bearer/Authorization, `KEY=value`) but is not
  exhaustive — treat `audit.jsonl` as sensitive and keep it out of shared locations.

## Eval model

- `guardrails.py` unit-tested on allow **and** block (100% line+branch); each hook script tested
  (block → exit 2, allow → exit 0, internal error → fail-open exit 0); `hooks.json` validated.
  mypy covers `plugin/hooks`.

## Beyond the hooks (shipped separately)

**Scheduling** (headless/CI cadence — knowledge-base re-scan, deploy-watch digests) and
**observability** (the audit-log digest) are not guardrails, so they live outside L4 — now
**built** in `schedule.py` / `observability.py` + the `run_scheduled` / `audit_digest` CLIs + a
cron workflow ([ADR 0024](decisions/0024-stage7-scheduling-observability.md)). A richer
observability dashboard remains an optional follow-on. L4 itself = the four hooks per CLAUDE.md.
