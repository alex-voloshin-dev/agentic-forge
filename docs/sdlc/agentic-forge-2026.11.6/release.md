---
type: release
feature: agentic-forge-2026.11.6
status: final
version: 2026.11.6
date: 2026-11-10
changelog:
  - "Changed: every on-listing skill description is shorter and leads with what the skill does; the shipped listing falls from 10,257 to 6,910 chars, and the Tier-0 ratchet moves down with it."
  - "Changed: `skill-factory` is a maintainer skill in the repository's `.claude/skills/` and no longer ships; a user's listing has 16 skills."
  - "Changed: the opt-in pre-router hook stays quiet on a request to build a skill, agent or component instead of nudging a domain skill."
  - "Fixed: the Tier-1 router runs with no tools, so it names a skill instead of running it, and no trigger prompt is left unmeasured."
breaking:
  - "`skill-factory` is gone from the installed plugin. It only ever worked inside this repository, where it is still available."
---
# Release 2026.11.6

Claude Code keeps one skill listing for every plugin and skill source together, by default 1% of the context window.
When the listing is over that budget, it keeps the names and drops the descriptions of the least-used skills. agentic-forge
took 10,257 chars of it. This release takes 6,910, without losing any routing quality.

## Upgrade notes

Upgrade from any earlier version.

- **`skill-factory` no longer ships.** It builds components of agentic-forge itself and its paths only resolve in this
  repository, where it is still loaded from `.claude/skills/`. If you used it elsewhere, it never worked there.
- Skill descriptions changed in wording only. The skills' bodies and behaviour did not change.
- If you enabled the pre-router (`pre_router.enabled`, off by default), it now says nothing on "create a skill for…" or
  "scaffold an agent that…", where it used to nudge `release`, `code-review` and similar.
- **Check for a second, synced copy of the plugin.** If your claude.ai account syncs plugins, `claude plugin list --json`
  may show `agentic-forge@synced` beside the installed one. On the maintainer's machine that copy was 2026.7.2, which
  predates this month's security fixes, and it loaded alongside the current release. Turn it off with
  `"enabledPlugins": {"agentic-forge@synced": false}` in `~/.claude/settings.json`.

## Measured

- **Tier-1, real model `claude-opus-4-8`, n = 5, fixed router:** 17/17 PASS (16 shipped skills plus `skill-factory`),
  recall 1.000 and specificity 1.000 each, 0 calls without a decision. The same router on the old descriptions (9c5adfa)
  also gives 17/17 at 1.000, so the shorter descriptions route exactly as the long ones did.
- **Tier-1b (activation), real model `claude-opus-4-8`:** pooled 0.938 (75/80 over 16 skills), PASS at the 0.80 gate.
  The last baseline on the old descriptions was 0.940 (79/84, ADR 0093), with `skill-factory` in the stand. Lowest:
  `develop` 3/5, `ux-design` 3/4, `knowledge` 4/5; at n = 4 to 5 per skill those are the noise the pooled gate exists for.
- **The router fix, A/B on the four affected prompts:** 5 of 12 calls without a decision before, 0 of 12 after. With the
  old router, `code-review`, `deep-review` and `deploy-watch` failed on unmeasured prompts on both old and new descriptions.
- Tier-0: `dev/validate.py` clean, with the listing at 6910/6910 and one maintainer skill validated. ruff and mypy clean.
  3781 tests pass, coverage 95.73%. `dev/hook_smoke.py` passes on Python 3.12 and on 3.9.25.
- The pre-router self-check over the 16 shipped skills: recall 0.463 (37/80), precision 0.974, wrong-skill 1,
  false-suggest 0/68, the same with the new veto and without it. The veto stays linear on 200 KB inputs.
- Reviews: three rounds with the reviewer and the external codex lens, then one confirming pass that the user approved
  after the third round escalated on a backtracking regex in the veto. A QA pass added 25 end-to-end tests.

## Not validated

- **Tier-2 and Tier-3 were not run.** Skill bodies did not change; only descriptions, the eval harness and the
  pre-router did.
- The pre-router veto on Python 3.9 was checked by hand in a container, not in the suite: the 3.9 image has no PyYAML,
  so the hook smoke stops before it reaches the scorer.
- macOS and Windows.

## Known limits and follow-ups

Recorded in ADR 0105. The veto misses some wordings ("create another skill", "set-up a new skill") and stays quiet on a
few that are not authoring requests ("add a test for agents"). It errs on the side of silence. `skill-factory`'s Tier-2
stand still ships under `plugin/eval/fixtures/`, as inert data like every other skill's stand. Next in the queue: the
external reviewer failing on a diff over 128 KiB and outside a trusted directory, then a fleet-coordination pattern.
