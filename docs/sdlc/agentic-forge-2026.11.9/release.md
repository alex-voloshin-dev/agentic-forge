---
type: release
feature: agentic-forge-2026.11.9
status: final
version: 2026.11.9
date: 2026-11-11
changelog:
  - "The eval extra moves from anthropic>=0.39 to >=2.8,<3, and constraints/ci.txt pins it (ADR 0108)."
  - "Tier-0 fails when the marketplace lists the plugin at another version than plugin.json."
  - "Fixed: the marketplace listed 2026.11.7 after the 2026.11.8 release."
breaking:
  - "--runner api needs anthropic 2.8 or later; reinstall the eval extra."
---
# Release 2026.11.9

This release finishes the dependency update the user ordered: the last step, the Anthropic SDK behind
`--runner api`, needed a live API run, so it ships on its own. It also fixes a slip in 2026.11.8 and adds the check
that would have caught it. No skill, agent or hook changes.

## What changed

- **`anthropic>=2.8,<3`** for the optional `eval` extra (was `>=0.39`). Only `--runner api` uses it: the per-token
  transport of `dev/run_agent_evals.py` and `dev/run_skill_evals.py`. 2.x sends API version 2026-10-21, which rejects
  sampling parameters, a document in an assistant message and citations in a user message. Our one Messages call
  sends none of them. The SDK's own changes (httpx2, Python 3.10 or later, per-role message types, the key sent as
  `Authorization: Bearer`) do not touch it either.
- **`constraints/ci.txt`** is now compiled with the `eval` extra too, so `pip install -c constraints/ci.txt -e
  ".[dev,eval]"` installs the tested SDK. CI still installs only `.[dev]`.
- **`api_runner`** selects text blocks with `block.type == "text"`, so strict mypy passes with the SDK installed. Same
  behaviour.
- **Tier-0 checks the marketplace version.** 2026.11.8 bumped `plugin.json` and left `.claude-plugin/marketplace.json`
  at 2026.11.7. `dev/validate.py` now fails when the marketplace entry for the plugin carries another version, and
  CONTRIBUTING's release steps name both files.

## Upgrade notes

- Plugin users: nothing to do; the marketplace now shows the right version.
- `--runner api` users: `pip install -c constraints/ci.txt -e ".[dev,eval]"`. A proxy that reads only `X-Api-Key`
  will not see the key, since 2.x sends `Authorization: Bearer`.

## Measured

- Live: `dev/run_agent_evals.py --runner api --role grader --runs 1`, anthropic 2.8.0, Python 3.15.2,
  `claude-opus-4-8`: every case passed, mean 1.000. The gate printed FAIL because one run is below its N >= 5 minimum;
  the run was meant to check the transport, not the role.
- Tier-0 on Python 3.15.2 with the SDK installed: `dev/validate.py` clean, ruff clean, mypy clean (63 files), pytest
  green with coverage 95.87%, `dev/hook_smoke.py` passes. mypy is also clean without the SDK, as CI runs it.

## Not validated

- Tier-1, Tier-1b, Tier-2 at N >= 5 and Tier-3: no skill, agent or hook changed.
- `--runner api` for the other roles and for `dev/run_skill_evals.py`; they use the same transport function.
- The `--runner api` default model is still `claude-opus-4-8`; refreshing model ids is queue item 6.

## Next

The queue on board `known-issues`: external_review's 128 KiB limit, vault folder loading, the handoff readiness
field, stack detection.
