---
name: release
description: Cut and tag a release — decide the next semver version and write that release's notes and changelog from ALL commits since the last tag (the whole release's aggregated changelog, not one PR's entry). Use to cut or prepare a release, tag a version, decide the next version number / bump, or write the release notes / changelog for a release. Not for adding a single CHANGELOG entry for one pull request during development (ordinary file editing, not a release), deploy/rollout monitoring (deploy-watch), or incident handling (incident-response).
allowed-tools: Read, Grep, Glob, Bash, Write, Edit
---

# Release (phase workflow)

The release phase of the SDLC spine: turn the merged work since the last tag into a proposed
**semver version** and a **Keep-a-Changelog** changelog, emit a `release` handoff artifact, and —
only when asked — tag. The deterministic logic lives in the installed `agentic_forge.release`
module; this skill wires it to the repo and renders the result. (Design:
[ADR 0021](../../../docs/architecture/decisions/0021-stage4-ops-seam-and-eval-tiers.md),
[quality-ops.md](../../../docs/architecture/quality-ops.md).)

## When to use

When the task is to cut/prepare a release, write release notes, assemble a changelog from merged
work, or decide the next version. **Not** for adding the per-PR `CHANGELOG` entry while developing
(that is docs discipline), monitoring a rollout (`deploy-watch`), or handling an incident
(`incident-response`).

## Process

The release helpers are an **installed module** — call them with Python, do not look for a file:

```
python -c "from agentic_forge import release; print(release.commits_since('.'))"
```

1. **Find the current version + the commits.** The current version is the latest tag
   (`git describe --tags --abbrev=0`) or the project manifest (`pyproject.toml` / `package.json`).
   Collect the commit subjects since that tag with `release.commits_since(repo)` — or, when you are
   handed an explicit commit list/file, read those lines instead (one message per line).
2. **Summarise.** `release.summarize(current, messages)` returns the proposed `version`, the `bump`
   level (breaking → major, `feat` → minor, else patch; pre-1.0 breaking → minor), the changelog
   `groups` (Keep-a-Changelog: Added / Changed / Deprecated / Removed / Fixed / Security), and the
   `breaking` descriptions. Conventional-commit prefixes drive the grouping; `chore`/`docs` and
   other uncategorised commits are kept out of the changelog as noise.
3. **Render the artifact.** Write a `release` handoff artifact (frontmatter `type` (= `release`),
   `feature`, `status`, `version`, `changelog`, `breaking`) plus human-readable notes, then validate
   it (`handoff.validate_header(header, expected_type="release")`; see
   [handoff.md](../../patterns/handoff.md)). Flag every breaking change prominently. Do not invent
   entries beyond the commits.
4. **Tag only on request.** Never create or push a tag unless explicitly asked; propose the
   command and let the user run it. Never rewrite history.

## Output

A `release` handoff artifact: the proposed version, the grouped changelog, and the breaking
changes — ready for the user to review and tag. Nothing is tagged or pushed without an explicit ask.

## Definition of done

- The proposed version applies the correct bump for the commits (breaking → major, `feat` → minor,
  else patch; pre-1.0 breaking → minor).
- The changelog is grouped into Keep-a-Changelog sections; breaking changes are called out;
  uncategorised commits (chore/docs) are omitted.
- The artifact validates as a `release` type (version + non-empty changelog); nothing fabricated.
- No tag is created or pushed without an explicit request.
