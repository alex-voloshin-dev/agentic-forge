# Amend mode: change an existing PRD in its own format

Most PRD work in a living repository is amending a PRD that already exists, not writing a new one.
This is the `product` skill's procedure for that. It replaces steps 1–6 of the skill; recall,
delivery isolation and `artifact-home` (the preamble) still apply.

## When

- The user points at an existing PRD ("add an export requirement to `features/in-progress/x/prd.md`").
- Or `artifact-home --kind prd` reports `artifact.exists: true` and the request changes the
  feature's requirements rather than starting one.

Never answer an amend request by writing a second PRD beside the first: two PRDs for one feature is
the failure this mode exists to prevent.

## 1. Locate and classify

- **Path**: the one the user named, else `artifact.path`.
- **Format**: `artifact.format` from `artifact-home`. For a path elsewhere, the same rule by eye: it
  is `handoff` only when its first line is `---` and that frontmatter says `type: prd`; anything
  else (a `| **Status** | … |` metadata table, another tool's header, plain headings) is `foreign`.
- **Clean start**: `git -C <worktree> status --porcelain -- <path>` must print nothing. If the file
  already has uncommitted changes, they are someone else's: ask when interactive; headless, change
  nothing and report it.

## 2. Edit in place, in its format

- Read the whole PRD and the request; gather what the change needs (a research brief if there is
  one, the code). Elicit load-bearing gaps when interactive; headless, take the most defensible
  reading and record it (step 4), as in create mode.
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

## 3. The gate (what `--gate-green` means in this mode)

- **Handoff format:** the read-back, exactly as in create mode:
  `python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" handoff-load --path <path> --type prd`.
- **Foreign format:** `handoff-load` is **not** the gate. It validates the plugin's YAML header, and
  a foreign PRD has none, so it would refuse every one of them. The gate is green when
  `git -C <worktree> diff --check -- <path>` exits 0 (no conflict marker or whitespace error) **and**
  `git -C <worktree> diff --stat -- <path>` shows the file changed (an amendment that changes
  nothing is not done).

## 4. The skeptic loop runs on the diff

The bounded loop is the skill's step 6, with these differences:

- The `reviewer` gets the diff (`git -C <worktree> diff -- <path>`; it may run that read-only git
  command itself) and the whole PRD for context. It attacks **the change**: each new or changed
  requirement testable, each metric measurable, nothing contradicting an untouched requirement,
  non-goals still complete, no id renumbered or reused, the format kept, and nothing changed
  outside the request.
- The external reviewer lens reviews the whole file:
  `python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/external_review.py" --target <worktree>/<path> --repo <worktree> --kind product`.
  A finding on text the amendment did not touch is out of scope unless the amendment caused it:
  record it in the round as a follow-up, do not fix it.
- **Each round** is `review-prd-<n>.md` in `<feature-dir>/` (`type: review`, `target` = the PRD's
  path, `iteration`, `verdict`, `findings[]`); recorded assumptions go in its body. Same lifecycle:
  on `proceed` keep only the final round, on `escalate` keep them all. That folder is where the
  non-convergence scan and the next phase look for it.
- **Exit:** `af.py review-decision` with this mode's gate, as in create mode.
  - `proceed`: a handoff-format PRD gets `review_decision: proceed` and is read back again. A
    foreign PRD has no field to set and gets none: the kept final round, `verdict: approve`, is the
    record. Commit the PRD **and** that round (`doc-proceed --artifact` once for each).
  - `escalate`: commit nothing, mark the feature PR a draft, keep every round. For a foreign PRD the
    rounds, ending at `changes`, are the only record that the amendment did not converge.

## 5. What the next phases do with it

`architecture` and `plan` read a handoff-format PRD through `handoff-load` and its `ready`, as
always. A foreign PRD has no `ready`: they build from it when the user points at it and say so in
what they write, and a latest round still at `changes` stops them from building on it unasked
([handoff.md](../../../patterns/handoff.md)). `develop` reads only `plan.md` and `tech-design.md`.

## Report

The PRD's path and format, a one-paragraph summary of the requirement change (not the whole diff),
the rounds and their verdicts, any assumption taken, and the delivery line from `doc-proceed`.
