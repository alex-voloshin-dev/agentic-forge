# ADR 0090 — The eval had nothing to work on

Status: Accepted (implemented)
Date: 2026-09-13

## Context

ADR 0088 measured unprompted skill activation and found a shape: four skills at 0.000 —
`code-review`, `develop`, `security-review`, `deep-review` — the ones with an obvious do-it-by-hand
path. ADR 0089 built a per-prompt hint, watched those four not move even with the exact skill name
in context, and concluded: *for them the bottleneck is not routing information; the model knows
and declines.* The next step in the roadmap was to rewrite their descriptions from "price list" to
value proposition, on the theory that the model was reading cost and no benefit.

Before rewriting anything, the plan called for one cheap diagnostic: resume every session that did
not invoke its skill and ask it, neutrally, why. `--ask-why` did that for all 36 misses of a run
with the pre-router on. The stated reasons, verbatim, for the four skills the rewrite was aimed at:

> *"there was no diff to review. My working directory was empty and not a git repo, so invoking
> the `agentic-forge:code-review` skill would have had nothing to operate on — I stopped to ask you
> where the change was"* — `code-review`, "Review this diff for bugs and security before I merge"

> *"I didn't actually do the work directly — I never got as far as building anything. My two
> attempts to inspect the working directory both came back empty … so I never located a plan"*
> — `develop`, "Build the task-priorities feature from the plan"

> *"I never audited anything. When I looked for a 'module' to audit, the only file in that
> directory was a PRD … not code. There was nothing to audit, so I stopped"* — `security-review`

> *"I couldn't, because there was no target: the working directory was empty and no docs were
> specified. So rather than invoke `deep-review` (or do the work myself), I stopped and asked you
> which docs you meant"* — `deep-review`

**Thirty-six of thirty-six** say a version of this. Twenty-three match the pattern by keyword; the
other thirteen say it in Russian (*"рабочая директория была пустой"*), or cite the request itself
— *"the request still contained the literal placeholder 'X'"* (`research`, `product`, `plan`:
their trigger prompts really do say "for X") — or *"the only file was a PRD"* (a `product`
activation earlier in the run had written one into the **shared** temp directory). Exactly one
answer in 36 is a preference: `deploy-watch`, *"a snap judgment that it was a trivial one-liner
status check"*.

The model was not doing the work by hand. It looked, found nothing to run the skill on, and asked
where the code was. The eval scored that as a miss.

### What was wrong with the stand

1. **One empty temp directory for all 84 prompts.** "Review my PR", "build from the plan",
   "audit this module" had no PR, no plan, no module. A session that asks for the missing input is
   behaving *correctly*; the harness counted it against the skill.
2. **Shared, not fresh.** Skills that did fire (`product`) wrote artifacts into the same directory
   the next prompts ran in, so later sessions found "a PRD and nothing else" and reasoned from
   that. Cross-prompt contamination, invisible from the numbers.
3. **Placeholder prompts.** Four trigger prompts contain a literal `X` — fine for the router
   (which classifies the *sentence*), fatal for activation (which runs it).
4. **The bucket classifier echoed the question.** *"you did the work directly — why?"* elicited
   "I didn't do the work directly…", and `directly` was a keyword of `task-is-simple`, which is how
   19 empty-workdir answers were filed under "the task was simple". The raw text was printed
   beside the tally precisely so this could be caught; it was, on first reading.

## Decision

1. **Every Tier-1b prompt runs in a fresh, realistic workspace.** `activation.prepare_workspace`
   copies the Tier-3 spine fixture (a small Python repo), seeds the SDLC artifacts a spine phase
   expects (`docs/sdlc/task-priorities/{research-brief,prd,tech-design,plan}.md`), `git init`s a
   `main` with a baseline commit, then checks out a feature branch with one committed change and
   leaves one unstaged edit — so `git diff`, `git diff main..HEAD`, "this branch", "the plan" and
   "this module" all exist. One directory per prompt; nothing carries over. `--empty-workdir`
   keeps the old condition only to reproduce the old numbers.
2. **The four placeholder prompts become concrete** ("for the task-priorities feature", "storing
   task priorities"). Trigger data is a contract: Tier-1 re-runs for those three skills.
3. **The buckets get a `nothing-to-work-on` bucket, first,** and lose `directly`.
4. **Two earlier conclusions are retracted in place** (the ADRs keep their text and gain a dated
   note, because the reasoning was sound on the data it had, and the data was wrong):
   - ADR 0088's *shape* — "a skill fires in inverse proportion to how easily the model can do the
     task itself" — is contaminated: the zeros are the *artifact-dependent* skills, which is a
     different property. The note's lift (0.333 → 0.560) is paired on the same stand and stands
     as a relative effect; the absolute levels do not.
   - ADR 0089's "the model knows and declines" is **not supported**. On that stand the model could
     not have invoked the skill on anything. The pre-router's null result on the hard four is
     uninterpretable, not negative.
5. **The description rewrite (ADR 0088 step 4) is deferred**, not cancelled: it was aimed at a
   cause the diagnostic did not find. It comes back only if the re-baseline on a real workspace
   still shows those four low *and* the stated reasons say cost.

## What survives

The field evidence does. 183 `Agent` calls against 3 `Skill` calls came from real repositories
with real diffs (ADR 0081), and the two headless checks on this repo (ADR 0088) had a real last
commit to review — the model ran `git show HEAD` and reviewed by hand. Low unprompted activation
with real targets is real. What this ADR removes is the *eval's* ability to say how low, and
every conclusion that rested on its absolute numbers. The next baseline is the first honest one.

## Consequences

- Two more measurement runs before any product change: the baseline on the real workspace
  (master: note on, pre-router off), then the pre-router on top. Each ~45 minutes.
- The diagnostic earned its place in the sequence. It cost one run and prevented rewriting four
  descriptions — under a listing budget with no headroom — to fix a reason the model does not
  have. "Measure, then decide" was not slower than guessing; it was the only step that was right.
- Self-reports remain claims, not measurements (ADR 0073). Here they were decisive because 36 of
  36 agreed on a fact the harness could verify — the directory *was* empty — not on a motive.
- A `--setting-sources project` run still answered in Russian in thirteen sessions. ADR 0077's
  amendment (project memory reaches an eval run) applies here too; it did not change the finding.

## Alternatives considered

- **Keep the empty workdir and count "asked for the input" as activation.** Rejected: it would
  make the metric mean "did not do it by hand", which is not the property anyone cares about.
- **Point every prompt at this repository.** Rejected: activation would then depend on whatever
  state this checkout happens to be in, and a `develop` prompt could edit it. A fixture copy is
  hermetic and the same for every run.
- **Rewrite the descriptions anyway, since it is cheap.** Rejected: it is the one budget with no
  headroom, and the reason it would address was not found.
