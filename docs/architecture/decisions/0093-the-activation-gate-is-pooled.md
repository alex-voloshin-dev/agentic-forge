# ADR 0093 — The activation gate is pooled: 79/84 = 0.940, floor 0.80

Status: Accepted (implemented)
Date: 2026-09-13

## Context

ADR 0092 left one measurement in the series: the Tier-1b baseline on the polished stand (content-
bearing prompts for `incident-response` and `knowledge`, a blog post and a task-list page in the
fixture, `--max-turns 4`), taken to calibrate the `--min-activation` gate that CI's `tiers:
activation` step (PR #54) runs without. Note on, one pass, every miss asked why:

```
1.00  architecture code-review deploy-watch develop incident-response knowledge marketing
      plan product qa-test-strategy repo-onboarding security-review skill-factory   (13 skills)
0.80  deep-review 4/5
0.75  release 3/4   ux-design 3/4
0.60  research 3/5

pooled 79/84 = 0.940   mean of rates 0.935   the "hard four" 18/19 = 0.947
```

Against ADR 0091's 78/84 on the same stand before the polish: the three prompts that presupposed
absent content are now 3 of 3 (`incident-response` 4/4, `knowledge` 5/5, `marketing` 9/9), and
`develop` no longer loses a prompt to the turn cap. Three of the five misses explained themselves:

| skill | what the session said | what it is |
|---|---|---|
| `deep-review` | "no principled one. I read the design … and started treating 'find everything wrong' as a review I'd just do myself, when the SessionStart reminder and the skill's own description …" | the ADR 0092 shape — momentum — one in 84 |
| `release` | "I judged the question as a narrow, read-only lookup ('just tell me the number') and decided a quick manual analysis was lighter-weight than spinning up the full release workflow" | a proportionality judgment, like ADR 0091's one |
| `ux-design` | "the feature is a headless Python library with no UI, so there were no WCAG/accessibility requirements to design" | a judgment about *the feature*, which is right: the page in the fixture is not the feature |

The other two — both `research` — had no explanation at all, and the progress line had **82 dots
for 84 prompts**. The runner prints a dot after a session that ends and nothing after one it kills
at `--timeout`; on a timeout it also threw the partial transcript away (`TimeoutExpired.stdout` is
bytes on POSIX, and the runner kept only `str`), so the session id went with it and the miss could
not be asked. Two 300-second sessions were scored as two `research` misses and left no trace.

The re-run of `research` alone then hit the account's usage limit: four of five sessions returned
*"You've hit your session limit · resets 4pm"* without an assistant turn, and the instrument scored
them as misses — `research` 0.200, and the new pooled verdict would have read the same. A gate
that reads a usage limit as a routing regression is worse than no gate.

## Why the gate is one number, not seventeen

A skill has 4-9 trigger prompts. The exact binomial for a full run of 17 skills (four with 4
prompts, twelve with 5, one with 9), at the true activation rates the two honest baselines put the
plugin at:

```
per-skill floor      P(some skill flakes in a healthy run)     P(a skill really at 0.6 is caught)
                     p=0.90   p=0.93   p=0.96                   n=4      n=5
  0.5                 11.2%    4.2%     0.8%                    17.9%    31.7%
  0.6                 27.8%   13.7%     4.3%                    52.5%    31.7%
  0.75                72.4%   47.8%    19.7%                    52.5%    66.3%

pooled floor (84)    P(FAIL) at true p:  0.571   0.75    0.85    0.90    0.93    0.94
  0.80                                   100%    87%     12%     0.4%    0.01%   0.003%
  0.85                                   100%    99%     50%     7.4%    0.55%   0.3%
  0.88                                   100%    100%    73%     22%     3.2%    1.8%
```

A per-skill floor loose enough not to flake (0.5) catches a skill that has really halved only one
time in three at n=5; one tight enough to catch it (0.75) fails a healthy plugin every other run.
There is no per-skill number that is both a gate and true. Pooled over 84 prompts, the same true
rate is a different instrument: 0.80 sits five sigma under the baseline, fails the note-off regime
(0.571, ADR 0092) with certainty, and catches a drop to 0.75 seven runs in eight.

0.85 was the other candidate: better power at 0.85, but 7.4% flake if the true rate drifts to 0.90
— a model version away, since the gate runs on whatever `EVAL_MODEL` is. A gate that is run on
demand and trusted has to be robust to that drift more than it has to see a 0.05 dip; the dip is
what the per-skill lines and the why-answers are for.

## Decision

1. **`--min-activation` gates the rate pooled over the run** (`activation.pooled()`), and CI's
   `tiers: activation` step runs `--min-activation 0.80`. The per-skill `ActivationReport` lost
   `passed`/`gated`/`reasons`: it is a lens, printed weakest-first, never a verdict. The mean of
   per-skill rates is printed beside the pooled rate and never gated. `--skill X` narrows the run,
   and then the pooled number *is* that skill's — with its n, which is why it is not a gate.
2. **A session that never got an assistant turn is `undetermined`** — a usage limit, an auth
   error, a crash, a timeout before the first token. It is out of the rate's denominator and listed
   with its error text (`never ran [research] …: You've hit your session limit`). When gated, more
   than `MAX_UNDETERMINED = 0.10` of the run's sessions undetermined **fails the run on that
   alone**: the number over the rest may be fine, but the run is not the measurement it claims to
   be. Under that share, a stray dead session is excluded rather than read as a miss.
3. **A timeout keeps its partial transcript and shows as `T`** in the progress line. A Skill call
   made before the kill counts; a session id survives so the miss can be asked; a miss with no
   session id at all records `NO_SESSION` as its reason instead of vanishing from the why-list.
4. **The baseline of record is 79/84 = 0.940** as the instrument reported it, with the two
   `research` timeouts scored as misses (the conservative reading). The `research` re-run after the
   limit reset is recorded below; it does not move the floor either way — at 0.80 the floor is
   robust to anything the honest baselines have measured.

## The `research` re-run, on the fixed instrument

Same stand, `--skill research`, after the limit reset: `TT..T` — three of the five sessions ran
past the 300-second timeout, and every one of them had invoked `agentic-forge:research` before the
kill. **5/5.** The two "misses" in the baseline were the same shape: a session that reached for the
skill, then ran the skill's own fan-out until the runner killed it — and the runner threw the proof
away with the transcript. Read with that, the polished stand is **81/84 = 0.964**; 79/84 stays the
number of record for the run as it was reported, and the floor holds under either.

*(Amended 2026-09-14, ADR 0094: the audit changed the stand again — eight skills' prompts carry
their referent, the fixture seeds a knowledge vault, every phase skill has an absence branch — so
79/84 no longer describes it. The re-baseline on the released tree reads **83/84 = 0.988**, sixteen
skills at 1.000, one `ux-design` miss that reads its prompt as a lookup. The floor stays 0.80: it
was calibrated against model drift, not against the current value.)*

## Consequences

- The activation gate is live and cheap to trust: one binomial with a known flake rate, run on
  demand (84 sessions, not weekly — ADR 0083), failing on a routing regression of the size this
  series has actually seen and on a run that did not happen, and on nothing else.
- Three of the five misses on the polished stand are judgments (two proportionality, one about
  the feature), one is momentum. The stand has stopped explaining misses; what is left is the
  model's, and at one in eighty-four it is not a problem to fix.
- Two instrument defects surfaced only because the run's misses were asked why and the dots were
  counted. The pattern of this whole series holds: read every miss, and count the prompts.
- A `research` session outlives the timeout *because it invoked the skill* — the fan-out is the
  long part. `--timeout` bounds the runner's wait, not the measurement, now that a partial
  transcript counts; raising it would only make the run slower.
