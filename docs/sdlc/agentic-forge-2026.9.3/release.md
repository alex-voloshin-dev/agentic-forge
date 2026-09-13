---
type: release
feature: agentic-forge-2026.9.3
status: final
version: 2026.9.3
date: 2026-09-13
changelog:
  - "Added: `SKILL_ROUTING_NOTE` in the SessionStart `additionalContext` (ADR 0088) — two sentences telling the session that agentic-forge skills are workflows with review gates and handoff artifacts, and to invoke the matching skill *especially when doing it directly looks straightforward*. Measured against the Tier-1b baseline on the same 84 prompts: unprompted activation **0.333 → 0.560** (+68% relative, z = 3.03), with all four zero-activation skills moving off zero and nothing that already worked regressing. `build_context` now returns the note unconditionally — a repo with no knowledge vault previously got no injection at all"
  - "Added: **Tier-1b activation** (`plugin/lib/agentic_forge/activation.py`, `dev/run_activation_evals.py`, ADR 0088) — runs each skill's should_trigger prompts through a REAL Claude Code session with the plugin loaded and scans the transcript for a `Skill` tool call. Tier-1 asks \"which skill?\" (a frame the model never enters alone) and Tier-3 runs skills the harness invokes; neither measured whether a live session reaches for a skill unprompted, which is what the field reports were about. A measurement, not a gate, and not on the weekly cron"
  - "Changed: `eval.yml` splits into three jobs sized to how often their subject changes (ADR 0083) — `wiring` on every trigger (free), **Tier-1 routing on the weekly cron**, Tier-2/Tier-3 **on demand only**; ~360 agent sessions do not fit a 6-hour GitHub job. Every job declares `timeout-minutes` and reports which tiers it measured"
  - "Fixed: the Tier-1 parser reads a decision whose answer comes **last** (ADR 0085) or **first** (ADR 0088) around its reasoning, and the tool-call spelling `Skill(x)` / `/x` (ADR 0087). 65 of ~800 router calls in one run were discarded for prose length or a word like `doesn't` while stating the correct answer; a correct *decline* on a should-not-trigger prompt was among them"
  - "Fixed: a skill-shaped terminal name that is not ours is `OTHER` — a decision, never a hit (ADR 0086) — and every should-trigger loss is attributed to its winner (ADR 0087)"
  - "Corrected: ADR 0087's first reading. The router drops the `agentic-forge:` prefix for EVERY skill, so a bare name is ours, not a built-in namesake; re-read correctly, **not one loss to an actual built-in** appears and ADR 0086's hypothesis (b) is unsupported"
breaking: []
---

# Release 2026.9.3

Two field bundles said the same thing and neither could prove it: the plugin's skills barely fire
in real work. 183 `Agent` calls against 3 `Skill` calls over 27 days. This release is the
investigation that found out why, the eval that makes it measurable, and the two-sentence fix that
moved the number.

## The chain

Every step of it was an instrument reading wrong before the thing it measured was wrong.

**The weekly guard was green and blind** (ADR 0082) — six scheduled runs finishing in ~28 seconds
with every model-backed step skipped for a missing token. It was hiding July recall numbers of
0.72–0.84 for four skills. Fixed: a scheduled run now fails when it cannot measure. Then the
numbers were taken rather than assumed, and all four were at **1.000** — fixed months earlier, and
nobody could tell, because the diagnostics channel records only failures.

**The weekly job was also too big to run** (ADR 0083): ~360 agent sessions against a 6-hour cap.
Split three ways — wiring free on every trigger, Tier-1 routing weekly, Tier-2/3 on demand.

**Then the router eval itself was wrong three times.** A reply that stated the correct answer after
one sentence of reasoning was discarded for length (0085); a skill chosen that was not ours was
counted as no decision at all (0086); a bare name was read as a built-in namesake when the router
in fact drops the prefix for everyone (0087, correcting itself the same day). 65 of ~800 calls in
one run were thrown away, including correct *declines*. Fixed, the eval reads **17/17 at recall
1.000**.

## Which left nowhere to hide

A routing eval at 1.000 and a field log at 3 `Skill` calls cannot both be describing the same
system — so the eval was measuring the wrong property. Tier-1 asks *"which skill fits?"*, a frame
the model does not enter on its own. Two headless sessions on this repo, plugin loaded, asked to
review code: both did it with `Bash` and `Read`, never called a skill, never named one.

**Tier-1b** (ADR 0088) measures the missing property — does a live session *reach for* the skill
unprompted — and the baseline came back at **0.347**. The shape mattered more than the mean: the
zeros were `code-review`, `security-review`, `develop`, `deep-review` — every skill with an obvious
do-it-by-hand path — and the top was `skill-factory` at **1.000**, which has no by-hand path at all.
A skill fires in inverse proportion to how easily the model can just do the task itself.

## The fix is two sentences

Aimed at that shape, not at the mean: skills are *workflows* with gates and handoff artifacts that
working by hand skips — invoke the matching one **especially when doing it directly looks
straightforward**. Injected through the SessionStart channel that already carries the vault map.

```
pooled         28/84 = 0.333  ->  47/84 = 0.560   (+68% relative, z = 3.03)
the four zeros ALL moved off zero
unmoved        skill-factory 1.000; nothing that worked regressed
```

It does not finish the job — at 0.560 the model still works by hand on nearly half, and the three
shapes with both a built-in namesake and an easy manual path sit at 0.200–0.250. The pre-router
hook now has a measured bar to beat rather than a hypothesis to argue.

## What was deliberately not done

No description and no skill name was changed anywhere in this release. Renaming `code-review` and
`security-review` was the obvious move at three separate points and was wrong at all three: the
data never showed a built-in taking a request from us. The listing budget has no headroom, and
spending it on a guess is the failure this whole chain is about.

## Verification

- Tier-0 clean; `pytest` green; `ruff`, `mypy` clean.
- Tier-1 routing: 17/17 at recall 1.000 / specificity 1.000.
- Tier-1b: 84 prompts, baseline and intervention, both recorded in ADR 0088.
