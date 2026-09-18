---
type: release
feature: agentic-forge-2026.9.5
status: final
version: 2026.9.5
date: 2026-09-18
changelog:
  - "Fixed: thirteen skills that write a handoff artifact now read it back with `load_artifact` before finishing, and the handoff pattern says frontmatter is data, not prose (ADR 0096). They validated the header dict they built rather than the YAML they typed, so one malformed value — a list with a gloss after it — left an artifact the next phase could not read, and the failure surfaced one phase later against the wrong skill"
  - "Fixed: `engineering-standards` separates the two trust-boundary duties (ADR 0099). The delegated engineer read 'validate input; parameterised queries' as one duty and wrote 'the name crosses a trust boundary, so it is bound as a parameter' — and stopped, five runs of five. A parameterised query prevents injection and still accepts an empty name, a 10 MB string or the wrong type"
  - "Fixed: `marketing` content files are the thing that gets published — no heading, no editorial note — and each is counted with `wc -m` against its platform band (X at most 280, LinkedIn 1,300-1,900), stated in the report, with the bands in the always-injected body (ADR 0099)"
  - "Fixed: the daily deploy digest reads the pipeline for the first time (ADR 0095). It handed `gh --repo` the repository path instead of `owner/name`; the slug now comes from the `origin` remote, and `gh` without a GitHub remote reports 'unavailable', never an empty and therefore healthy pipeline"
  - "Fixed: `diagnostics-bundle` prints the record counts the skill tells the operator to report, and the skill quotes the command's three lines verbatim (ADR 0096)"
  - "Added: the always-on listing budget is a Tier-0 ratchet (ADR 0095) — measured, printed on every validate run, failing growth rather than size"
  - "Fixed (maintainers): Tier-2 graded the INSTALLED plugin, not the tree under test — ten skill bodies call scripts via `${CLAUDE_PLUGIN_ROOT}` and the harness set it nowhere (ADR 0097). Tier-2 and Tier-3 now pin it"
  - "Added (maintainers): the harness says what it measured (ADR 0098) — a provenance line on every run, a failing Tier-2 case kept in its own words, the `${VAR}`s a body may use held to a Tier-0 contract, and a failing assertion named under the pass-rate"
breaking: []
---

# Release 2026.9.5

2026.9.4 swept the plugin for three shapes of defect and fixed about fifty of them. This release is
what the evals said once they could finally see the tree they were grading — and that took three
fixes to the evals themselves before they could.

## The evals learned to say what they measured

A Tier-2 FAIL used to print a pass-rate and nothing else. Now it names the assertion that failed and
keeps one failing case in its own words (ADRs 0096, 0098). The first time it did, it named a
`diagnostics-bundle` assertion failing five runs out of five, and one transcript later the session
had diagnosed itself:

> *"Resolved the active plugin (`CLAUDE_PLUGIN_ROOT` was unset) to the installed version
> agentic-forge 2026.9.3 and ran its `build_bundle.py`…"*

Ten skill bodies call their scripts through `${CLAUDE_PLUGIN_ROOT}`, and the harness set it nowhere
— so for those skills Tier-2 had been grading the plugin installed on the maintainer's machine, not
the change under review (ADR 0097). In CI, where nothing is installed, the scripts could not be found
at all. Every run now starts with a line saying which tree it measures:

```
measuring: plugin=…/agentic-forge/plugin version=2026.9.5 git=… model=… home=… python=…
```

and the variables a skill body may lean on are a contract the harness pins and a Tier-0 test
enforces, so the next one cannot fall into the same gap.

## What it found once it could see

With the plugin root pinned, Tier-3 held at **5/5** — now about the tree it claims — and the
script-invoking Tier-2 contracts passed. Behind the passing numbers, the new evidence lines showed
rules that the skills state and the model does not follow:

- **A handoff validated as a dict, never as a file.** Thirteen skills checked the header they built
  and not the YAML they typed; a single list with a gloss after it made a correct test strategy
  unreadable to the next phase. They now read the file back, and frontmatter is data (ADR 0096).
- **Parameterise read as validate.** The standards pack named both duties in one breath; the
  engineer bound the value as a parameter and considered the boundary checked. Separated, the
  assertion that failed 5/5 went to **1.000** on the first pass (ADR 0099).
- **A length rule in a file nobody opened.** Marketing's character bands lived in a reference the
  session never loads; it took five passes, each named by the transcript, to move the rule, then
  its numbers, into the body — and to find that one assertion had been asking a read-only grader to
  count characters (ADR 0099). **PASS 0.985.**

The lesson under all of them: a rule stated in passing is followed in passing. The rules that hold
are phrased as an action at the moment of writing — *count the file*, *quote the line*, *read it
back*, *check the value where it enters*.

## For operators

- The **daily deploy digest reads the pipeline** for the first time: it resolves `owner/name` from
  the checkout's `origin` instead of handing `gh` a path, and says *unavailable* when there is no
  GitHub remote rather than reporting an empty pipeline as healthy (ADR 0095).
- **`diagnostics-bundle` prints its record counts**, and the report quotes the command's lines, so
  the path it gives you is the absolute one.

## Verification

- Tier-0: validate, ruff, mypy, full suite at 95.6% coverage; hooks smoke-run under CPython 3.9.
- **Tier-1** 17/17 at recall / specificity 1.000 and **Tier-1b** 83/84 = 0.988 — measured on
  2026.9.4; no skill description or trigger list has changed since, so both still describe this tree.
- **Tier-3** 5/5 scenarios, 20 phases, with the plugin root pinned.
- **Tier-2**, pinned: `diagnostics-bundle` 0.945, `engineering-standards` 1.000, `marketing` 0.985,
  `ux-design` 0.971, `pr-watch` 0.986; the other contracts' bodies changed only by the read-back
  sentence, and the skills behind them passed as Tier-3 phases on the same tree.
