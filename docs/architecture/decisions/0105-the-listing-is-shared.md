# ADR 0105 — The listing is shared, so ours gets shorter

Status: Accepted (implemented)
Date: 2026-11-08

Extends [0095](0095-the-budget-and-the-slug.md) (the listing budget as a Tier-0 ratchet) and
[0004](0004-skill-centric-router.md) (router discipline). Leaves [0091](0091-the-first-honest-baseline.md) standing:
0091 cancelled description edits *as a fix for activation*; this edits them to save listing space and gates the edit on
the routing eval, not on activation.

## Context

ADR 0095 made the always-on listing a ratchet at 10,400 chars and printed the figure on every run: 10,257 chars,
about 2,560 tokens, 17 skills. CLAUDE.md called that "at/over the ~1% ceiling". What it did not say is whose ceiling.

The Claude Code docs (skills, settings reference) answer that:

- The budget is one listing for every source together (built-in skills, user and project skills, every plugin), by
  default 1% of the context window (`skillListingBudgetFraction`, default `0.01`). The docs give no per-plugin share.
- Over budget, Claude Code keeps every **name** and drops **descriptions**, starting with the skills invoked least.
  A skill that keeps its name and loses its description cannot be routed to by what it does.
- Each description is cut at 1,536 chars (`skillListingMaxDescChars`). Ours are all under 800.
- `disable-model-invocation: true` takes the description out of context. `user-invocable: false` saves nothing.

Measured on the maintainer's own machine on 2026-11-08, with plugins synced from a claude.ai account:

| Source | Skills | Description chars |
| --- | --- | --- |
| `small-business@synced` | 44 | 34,615 |
| account skills synced from claude.ai | 28 | 17,340 |
| `agentic-forge` (installed, 2026.11.5) | 17 | 10,257 |
| `agentic-forge@synced` (2026.7.2) | 17 | 9,870 |
| five other synced plugins | 39 | about 11,700 |

About 84,000 chars in all, roughly twice the default budget, and the session showed it: dozens of skills from other
plugins were listed by name alone. Ours kept their text because they are used. In a session where they are not, ours
are the ones that go dark.

So the cost of our listing is not the 2,560 tokens it adds to context. It is the share of a common budget it takes
from everything else, and the risk that our own descriptions are dropped where we are a guest. Two of our 17 skills
also cost every user for a reason that does not apply to them:

- `skill-factory` builds components *of agentic-forge*. Its body names `plugin/skills/<name>/`, `plugin/agents/` and
  `plugin/schemas/evals.schema.json`, which exist only in this repository. In a user's project it can only misfire.
- The descriptions carried long "Not for X (Y)" tails, written one routing fix at a time (ADR 0029), and repeated
  synonyms ("cut or prepare a release, tag a version, decide the next version number / bump").

The same measurement found a second copy of the plugin, 2026.7.2, synced from the account and loaded beside the
installed release. It predates the five security fixes of this month. That is user configuration, not plugin code: it
is recorded here because it is how the listing was found to be doubled, and it was switched off in the maintainer's
user settings (`"agentic-forge@synced": false`).

## Decision

**1. Every on-listing description is rewritten to lead with what the skill does and to keep only the discriminators
the routing eval tests.** One clause for the job, one for when to use it, one naming the neighbours it must not take
from. The words that fixed past routing losses stay: the `INTO` and "producing the brief is research" of `product`,
"a test or QA plan is qa-test-strategy" of `plan`, "however deep" of `security-review`, "even of a PR" of
`deep-review`. Synonym lists and repeated boundary clauses go. No `: ` and no ` #` inside a description, so the
frontmatter stays plain YAML.

**2. `skill-factory` becomes a maintainer skill.** It moves from `plugin/skills/skill-factory/` to
`.claude/skills/skill-factory/` in this repository. Claude Code loads a project's `.claude/skills/` for any session
whose working directory is the repository, worktrees included, so the maintainer keeps it, model-invocable, under the
bare name `skill-factory`. It no longer ships, so it leaves every user's listing. Its gate does not change:

- Tier-0 validates `.claude/skills/*` with the same `validate_skill` as the plugin's skills. The listing budget does
  not count it, because it is not shipped.
- Tier-1 measures it against the listing a maintainer actually sees: the plugin's on-listing skills plus the
  maintainer skills. The other skills are measured with it present, as before.
- Tier-2 resolves a skill in the plugin first, then in the maintainer root.
- The pre-router hook ships, so it reads only shipped skills and no longer names `skill-factory`.

How that is built:

- Tier-0: `validation.validate_maintainer_skills(repo_root, plugin_dir)`, called by `dev/validate.py`, which already
  derives the repo root as the plugin's parent for doc-sync. `validate_plugin` keeps its meaning for a standalone plugin
  dir. The maintainer skills also get the ADR 0104 inline-Python checks, which are about skill bodies, and a rule that
  no maintainer skill shares a name with a shipped one, since the plugin would shadow it in Tier-2. They do not get the
  Python 3.9 rule: no user's `python3` runs them.
- The eval stand stays in `plugin/eval/fixtures/skill-factory/`. A contract's `files` resolve against the plugin dir in
  Tier-0, in `eval_case_problems` and in `materialize_fixtures`, and the skill's cases seed the real
  `schemas/evals.schema.json` by name, so moving the stand would mean a second resolution base through the shared
  Tier-2 core or paths that climb out of the plugin. It ships as inert data beside every other skill's stand. Whether
  eval fixtures should ship at all is a question for all of them, not this one.
- Tier-1: `tier1_runner` takes `skill_roots`; their skills are sorted into the listing by name and shown by their bare
  name, also under `--with-builtins`, where only the plugin's are namespaced. `dev/run_tier1_evals.py` passes
  `<repo>/.claude/skills` by default when it exists; `--no-maintainer-skills` measures the shipped listing alone.
- Tier-1b does not measure `skill-factory`. The activation stand is a fresh repo with `--plugin-dir`, which has no
  `.claude/skills`, so the skill would not exist there. `run_activation` reads shipped skills only, and the pooled stand
  is 80 prompts instead of 84.
- The maintainer root is read only in this repository: `validation.maintainer_root` returns it only when
  `docs/architecture/meta-core.md` exists, so `dev/validate.py ~/some-plugin` never reads a user's `~/.claude/skills`.
  The eval CLIs share one resolver (`_eval_cli.resolve_skill_roots`); an explicit `--skill-root` that does not exist is
  an error. The provenance line names the roots and counts an edit in them as `+dirty`; the plugin and each root are
  checked in their own repository, and a status check that fails reads `+status-unknown`, never clean.
- The pre-router lost the owner of every "create a skill / agent for X" prompt, and the purpose words then won: "create
  a skill for release notes" went to `release`, "scaffold an agent that reviews diffs for security" to `code-review`.
  It now abstains on an authoring verb in any inflection (create, scaffold, build, add, make, write, author, generate,
  implement, design, set up), then "a", "an" or "new", at most two more words, then skill, subagent, agent or component
  (`pre_router.is_authoring_request`). The article is what keeps it narrow: "build the plugin and cut a release" still
  goes to `release`, and "make the agent faster" is not vetoed. "plugin" is not a noun, because "build the plugin" is a
  release step in this plugin's own prompts and a whole new plugin is not `skill-factory`'s job. No shipped trigger prompt matches the veto, so the leave-one-out self-check is
  the same with it and without it: recall 0.463 (37/80), precision 0.974, wrong-skill 1, false-suggest 0/68, against
  0.488 (41/84), 0.976, 1, 0/71 before the move.
- `deep-review`'s description says "for a quick standard lint of a small diff use code-review". The first rewrite's
  "a quick lint of a small diff is code-review" put the bigram `quick lint` into deep-review's pre-router profile, and
  its own anti-trigger "Quick lint of this one-line change" was suggested to it.

**3. The ratchet moves down to the new size.** `LISTING_BUDGET_CHARS` is today's figure, as ADR 0095 defines it, so
the saved space cannot quietly fill again: a later skill or longer description is a visible budget review.

## Alternatives

- **Take more skills off-listing** (`marketing`, `ux-design`, `incident-response`). Rejected for now. Off-listing means
  the model never picks the skill on its own, which is the feature (ADR 0004), and there is no field data showing
  these go unused. `marketing` overlaps a separate marketing plugin, but users without it lose a skill.
- **Raise `skillListingBudgetFraction` in the plugin.** Not ours to set: it is a user setting, and it would buy room
  for us by spending the user's context.
- **Merge the three review skills.** A larger change to routing and to three Tier-2 contracts, for about 700 chars.
  Not worth it while the rewrite saves more with no change of behaviour.
- **Keep `skill-factory` in the plugin as `disable-model-invocation: true`.** Saves the same space, but the maintainer
  could then only reach it by typing `/agentic-forge:skill-factory`; the model could not choose it when asked to build
  a component, which is the one place it is meant to fire.

**4. The Tier-1 router runs with no tools.** Gating this change found a harness defect older than it. The router
call passed `--allowedTools ""`, which grants nothing and removes nothing (the limit `claude_cli_runner` itself
documents, ADR 0103), so the router kept the default tools, `Skill` among them. On some prompts it ran the skill it
was asked to name and answered in prose about an empty working directory. Each such call scored "no decision", and a
prompt whose five calls all did was left out as unmeasured, which fails the skill: four prompts in a full run,
failing `code-review`, `deep-review` and `deploy-watch`, on the base descriptions (9c5adfa) exactly as on the new
ones. `_build_router` now passes `--tools ""` as well. On the affected prompts, measured live: 5 of 12 calls without a
decision before, 0 of 12 after. The router's instruction and parser are unchanged.

## Exit criteria

- Tier-1 green for every on-listing skill, `skill-factory` included, at the unchanged 0.9 thresholds, on the new
  descriptions.
- Tier-0, pytest, ruff, mypy and the hook smoke under Python 3.9 green.
- `LISTING_BUDGET_CHARS` equals the measured listing.

## Consequences

- The shipped listing falls from 10,257 chars (17 skills) to the figure in the table below (16 skills).
- A user who built agentic-forge components with `skill-factory` loses it. That was never supported outside this
  repository: the skill's paths only resolve here.
- Tier-1 counts change from 17 skills to 16 shipped plus one maintainer skill. Tier-1b measures the 16 shipped skills.
- Not validated by this change: Tier-2 and Tier-3. Only descriptions changed in the shipped skills, and their bodies,
  which those tiers grade, are untouched.

| Measurement | Before | After |
| --- | --- | --- |
| Shipped listing | 10,257 chars, 17 skills | 6,910 chars, 16 skills (`LISTING_BUDGET_CHARS = 6_910`) |
| Tier-1, old router (`--allowedTools ""` only) | 3 skills FAIL on unmeasured prompts (9c5adfa) | the same 3 FAIL the same way; every measured prompt 1.000 |
| Tier-1, fixed router (`--tools ""`), claude-opus-4-8, n = 5 | 17/17 PASS on the old descriptions (9c5adfa), 1.000 / 1.000 each | 17/17 PASS (16 shipped + `skill-factory`), recall 1.000 and specificity 1.000 each, 0 calls without a decision |
