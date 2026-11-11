# ADR 0108 — The eval extra moves to the anthropic 2.x SDK

Status: Accepted (implemented)
Date: 2026-11-11

Completes the dependency update of [0107](0107-ci-measures-the-code-not-the-day.md), which left this step out because it
needs a live API run.

## Context

The optional `eval` extra pins the Anthropic Python SDK for one code path: `agent_eval.api_runner`, the `--runner api`
transport of `dev/run_agent_evals.py` and `dev/run_skill_evals.py` (per-token billing; the recommended `--runner claude`
uses the `claude` CLI and no SDK). The floor was `anthropic>=0.39`. The current release is 2.8.0.

The 2.x line changes three things that could touch us:

- It sends API version `2026-10-21` by default. That version rejects `temperature`, `top_p` and `top_k` on every
  model, a `document` block in an `assistant` message, and `citations` on `text` blocks in a `user` message, and drops
  deprecated Admin API fields.
- It is built on `httpx2`, requires Python 3.10 or later, removes deprecated parameters and aliases, sends the API key
  as `Authorization: Bearer`, and types `MessageParam` per role.
- It ships type information, so `mypy --strict` checks our calls against it whenever the extra is installed.

## Decision

1. **`anthropic>=2.8,<3`.** Our one call sends `model`, `max_tokens`, `system` and one user message as plain dicts, and
   reads `content`, `stop_reason` and `usage`. None of the version's breaking changes apply, and the SDK's own breaking
   changes do not touch it: no sampling parameters, documents, citations, Admin API, custom base URL, custom HTTP
   client or `X-Api-Key` header. Python 3.10 is below our 3.11 floor.
2. **`constraints/ci.txt` covers the extra.** It is now compiled with `--extra dev --extra eval`, so
   `pip install -c constraints/ci.txt -e ".[dev,eval]"` installs the pinned SDK and its dependencies. CI still installs
   only `.[dev]`; constraints never install anything on their own.
3. **The runner reads text blocks by `block.type == "text"`,** not `getattr(block, "type", None)`. With the SDK
   installed, mypy narrows the content union only on the attribute itself; the `getattr` form was 11 strict-mode
   errors. Behaviour is unchanged: every content block has a `type`.
4. **Tier-0 checks that the marketplace lists the plugin's own version.** The 2026.11.8 release bumped `plugin.json` and
   left `.claude-plugin/marketplace.json` at 2026.11.7; nothing caught it. `validation.validate_marketplace` fails when
   the marketplace has no entry for the plugin or lists it at another version. It runs from `dev/validate.py` whenever
   the repository has a marketplace file. CONTRIBUTING's release steps now name both files.

## Verification

Live, on 2026-11-11: `dev/run_agent_evals.py --runner api --role grader --runs 1` with anthropic 2.8.0 on Python 3.15.2
against `claude-opus-4-8`. Every case passed (mean 1.000). The gate reported FAIL only because one run is below its
N >= 5 minimum, which was the intent: the run checks the transport, not the role.

## Consequences

- `--runner api` users must upgrade the SDK: `pip install -c constraints/ci.txt -e ".[dev,eval]"`.
- A proxy or gateway in front of the API that reads only `X-Api-Key` will not see the key, since 2.x sends
  `Authorization: Bearer`. The plugin sets no base URL; a user who points `ANTHROPIC_BASE_URL` at such a proxy has to
  configure it.
- The default model of `--runner api` (`claude-opus-4-8`) is unchanged. Refreshing model ids belongs to the
  subagent-cost item in the queue.
- The SDK's license is Apache 2.0, as it was.
