# Amend mode: change an existing PRD in its own format

Most PRD work in a living repository is amending a PRD that already exists, not writing a new one.
This is the `product` skill's procedure for that. It replaces steps 1–6 of the skill; recall,
delivery isolation and `artifact-home` (the preamble) still apply.

## When

- The user points at an existing PRD ("add an export requirement to `features/in-progress/x/prd.md`").
- Or `artifact-home --kind prd` reports `documents.prd.exists: true` and the request changes the
  feature's requirements rather than starting one.

Never answer an amend request by writing a second PRD beside the first: two PRDs for one feature is
the failure this mode exists to prevent.

## 1. Locate the file in the worktree, never the checkout

**The file you edit is always the worktree's copy**, `<worktree>/<path>`, with `<path>` relative to
the repository's top. The user's editor shows the main checkout; its copy is never edited — the
delivery commits from the worktree, so an edit in the checkout is lost or, worse, committed by
nobody and left behind in the user's tree.

- **A PRD the user named:** let `artifact-home` map it —
  `python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" artifact-home --repo <worktree> --slug <feature-slug> --kind prd --path <file>`.
  An absolute `<file>` in any checkout of the repository (`/home/u/repo/features/x/prd.md`) becomes
  the same relative path under `<worktree>`; a relative one is read against `<worktree>`. A path
  outside a working tree, or whose folders hold anything but letters, digits, `.`, `_` and `-`, is
  refused (exit 1): ask the user, or, headless, stop and report.
- **Otherwise:** `documents.prd` from the preamble's call.
- **Its `artifact` is what you work on**: `abs` (the worktree file), `arg` (that path, quoted) and
  `commands` (`status`, `diff`, `diff_check`, `diff_stat`, `restore`, `handoff_load`,
  `external_review`, each with the path quoted). Run those verbatim; never type the path into a command yourself.
- **`exists: false`** means the worktree does not have the file: it is uncommitted or unmerged in the
  checkout, or on another branch. Interactive, say so and ask (commit or merge it first, or point at
  another file); headless, change nothing, stop and report. Do not copy it over from the checkout.
- **`unsafe` set** (a symlink, or not a regular file): never edit through it; stop and report.
- **Format**: `artifact.format`: `handoff` when it opens with `---` and its frontmatter says
  `type: prd`, else `foreign` (a `| **Status** | … |` metadata table, another tool's header, plain
  headings).

## 2. Start clean, and clear the previous amendment's round

Run **both** status commands `artifact-home` printed: `commands.feature_status` (the feature
folder's `git status --porcelain`) **and** `artifact.commands.status` (the PRD's own). A PRD named
with `--path` can live outside the feature folder, where the first does not look; pending changes
reported by **either** count.

Every file command below is one `artifact-home` printed, run from `<worktree>` (`git -C <worktree>`
built in, every path quoted): never type a path into `git` or `rm` yourself. The feature folder's
rounds are its `rounds` list (`review-<artifact>-<n>.md`, sorted by artifact, then iteration as a
number), each with `commands.git_rm` (a committed round) and `commands.delete` (an uncommitted one).

- **Nothing pending:** go on. If `rounds` holds a kept round of an earlier, finished amendment
  (`artifact: prd` whose `verdict` is `approve`), delete it now with its `commands.git_rm`; the
  removal is committed with this amendment, so this loop's rounds start again at 1 and "the latest
  round" always means this amendment's.
- **The plugin's own escalated leftover:** the only pending changes are this PRD and
  `review-prd-<n>.md` rounds, and the round with the **highest iteration** (compare the numbers, not
  the names) has `verdict: changes`. That is an earlier amendment that escalated and committed
  nothing. Interactive, show its unresolved findings and ask: resume from it (carry on at the next
  iteration) or discard it (`artifact.commands.restore` puts the PRD back as committed; each of
  those rounds' `commands.delete` removes it). Headless, leave it as it is, stop and report: the
  user decides.
- **Anything else pending in the PRD or the folder:** it is someone else's edit. Interactive, ask;
  headless, change nothing, stop and report.

## 3. Edit in place, in its format

- Read the whole PRD and the request; gather what the change needs (a research brief if there is
  one, the code). Elicit load-bearing gaps when interactive; headless, take the most defensible
  reading and record it (step 5), as in create mode.
- **Keep its format.** The metadata block (rows, their order and spelling), the headings, the
  requirement ids and their scheme (a new one takes the next free id, e.g. `FR-13` after `FR-12`;
  never renumber or reuse), the language and the line style all stay as they are.
- **Change only what the request asks, and what it forces** (a removed goal takes its acceptance
  criteria and metrics with it; a new requirement gets testable acceptance in the PRD's own way of
  writing it).
- **Foreign format:** add no YAML frontmatter, convert no table, and leave its status row alone
  unless the user asks: like `status`, it is the repository's lifecycle field. Assumptions go where
  the PRD's own structure has a place for them (an "Open questions" or "Assumptions" section);
  otherwise only in the review round and the summary.
- **Handoff format:** edit the header lists and the body together, and set
  `review_decision: revise` until the loop exits.

## 4. The gate (what `--gate-green` means in this mode)

- **Handoff format:** the read-back, exactly as in create mode: `commands.handoff_load`, the printed
  form of `python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" handoff-load --path <path> --type prd`.
- **Foreign format:** `handoff-load` is **not** the gate. It validates the plugin's YAML header, and
  a foreign PRD has none, so it would refuse every one of them. The gate is green when
  `commands.diff_check` (`git diff --check -- <path>`) exits 0 (no conflict marker or whitespace
  error) **and** `commands.diff_stat` shows the file changed (an amendment that changes nothing is
  not done).

## 5. The skeptic loop runs on the diff

The bounded loop is the skill's step 6, with these differences:

- The `reviewer` gets the diff (`commands.diff`, a read-only `git diff -- <path>` it may also run
  itself) and the whole PRD for context. It attacks **the change**: each new or changed requirement
  testable, each metric measurable, nothing contradicting an untouched requirement, non-goals still
  complete, no id renumbered or reused, the format kept, and nothing changed outside the request.
- The external reviewer lens reviews the whole file: `commands.external_review`, the printed form of
  `python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/external_review.py" --target <path> --repo <worktree> --kind product`.
  A finding on text the amendment did not touch is out of scope unless the amendment caused it:
  record it in the round as a follow-up, do not fix it.
- **Each round** is `review-prd-<n>.md` in `<feature-dir>/` (`feature_abs`): `type: review`,
  `target` = the PRD's repository-relative path, `iteration`, `verdict`, `findings[]`; recorded
  assumptions go in its body. Same lifecycle: on `proceed` keep only the final round, on `escalate`
  keep them all. "The latest round" is always the one with the highest `iteration`. That folder is
  where the non-convergence scan and the next phase look for it.
- **Exit:** `af.py review-decision` with this mode's gate, as in create mode.
  - `proceed`: a handoff-format PRD gets `review_decision: proceed` and is read back again. A
    foreign PRD has no field to set and gets none: the kept final round, `verdict: approve`, is the
    record. Commit the PRD **and** that round, and the deletion of the previous amendment's round
    if step 2 made one (`doc-proceed --artifact` once for each).
  - `escalate`: commit nothing, mark the feature PR a draft, keep every round. A handoff-format PRD
    gets `review_decision: escalate` (never its `status`). For a foreign PRD the rounds, ending at
    `changes`, are the only record that the amendment did not converge.

## 6. What the next phases do with it

`architecture` and `plan` read a handoff-format PRD through `handoff-load` and its `ready`, as
always. A foreign PRD has no `ready`: they build from it when the user points at it and say so in
what they write, and a latest round (the highest `iteration`) still at `changes` stops them from
building on it unasked ([handoff.md](../../../patterns/handoff.md)). `develop` reads only `plan.md`
and `tech-design.md`.

## Report

The PRD's repository-relative path and format, a one-paragraph summary of the requirement change
(not the whole diff), the rounds and their verdicts, any assumption taken, and the delivery line
from `doc-proceed`.
