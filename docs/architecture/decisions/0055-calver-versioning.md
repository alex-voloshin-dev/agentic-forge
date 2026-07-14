# 0055 — CalVer plugin versioning: `<year>.<month>.<inc>`

Status: Accepted — implemented (tooling + docs; the first CalVer release is the next cut, `2026.7.1`).

## Context

The plugin has versioned by semver (`0.1.0` was the first tagged release). Semver's core promise —
the version string encodes API compatibility — does not map onto what this plugin is: a
continuously-delivered bundle of skills, hooks, and prompts where "breaking" is rarely a type
signature and users have exactly one sensible upgrade move (take the latest). Field diagnostics
made the cost concrete: a production bundle arrived from plugin `0.0.1` while `0.1.0` was current,
and nothing in the version said *how stale* that was. A date-carrying version would have.

## Decision

Adopt CalVer for the plugin version and its git tags:

- **Format:** `<year>.<month>.<inc>` — e.g. `2026.7.1`. No zero-padding on month or inc
  (`2026.7.1`, not `2026.07.01`); this keeps the string a **valid semver triple** (semver forbids
  leading zeros), so anything that compares versions semver-style keeps working.
- **`inc` restarts at 1 each calendar month** (UTC) and increments per release within the month;
  a hotfix is simply the next inc. Ordering is monotonic within a month (`2026.7.2 > 2026.7.1`),
  across months (`2026.8.1 > 2026.7.9`), across years (`2027.1.1 > 2026.12.9`), and across the
  migration itself (`2026.7.1 > 0.1.0`) — no epoch tricks needed.
- **Breaking changes move entirely to the changelog.** `release.summarize` still classifies
  commits (the `bump` level and `breaking` list feed the notes); the version string no longer
  encodes them. A release with a breaking change gets the same date-based version, prominently
  flagged **BREAKING** in the notes.
- **Tags:** `v<calver>` (e.g. `v2026.7.1`). Existing semver tags stay; history is not rewritten.
- **Mechanics:** `release.next_calver(current, year=, month=)` (pure; the caller supplies the UTC
  date) computes the next version; `release.looks_calver(version)` lets the `release` skill detect
  a repo's scheme mechanically — **CalVer when the current version already is CalVer** (or the repo
  documents it, as this ADR does for agentic-forge), semver otherwise, so the skill keeps serving
  target repos that version semantically.

## Migration (from 0.1.0)

1. Tooling + docs land first (this ADR; `next_calver`/`looks_calver`; the release skill's process
   step; the CHANGELOG convention note). The manifest stays `0.1.0` until a release is cut.
2. The **next release** is cut as `2026.7.1` (or the then-current UTC month): plugin.json
   `version`, the CHANGELOG section heading, and tag `v2026.7.1`. The month counter starts at 1
   under the new scheme regardless of earlier same-month semver releases.
3. Nothing else changes: Keep-a-Changelog grouping, the release handoff artifact, and the
   "tag only on explicit request" rule all stay.

## Alternatives considered

- **Stay on semver:** rejected — the compat semantics are fictional for a skills bundle, and the
  version carries no freshness signal (the one fact support/triage actually needs).
- **`YYYY.MM` zero-padded (classic CalVer):** rejected — `2026.07.1` is not valid semver (leading
  zero), which risks breaking any semver-parsing consumer (marketplace update checks, tooling).
- **`YYYY.MM.DD` date-only:** rejected — collides on two releases in a day and encodes more
  precision than needed; a monthly counter reads cleaner (`2026.7.3` = third July release).
- **Epoch/major-prefix schemes (`1!2026.7`):** rejected — non-standard, breaks semver parsing.

## Consequences

- A version now answers "how old is this install?" at a glance — the exact question the 2026-07-14
  field bundle could not answer (fixed alongside: the bundle now ships the manifest + version).
- Version comparisons stay valid semver everywhere; no upgrade-flow changes.
- The `release` skill gains one mechanical branch (scheme detection via `looks_calver`); its
  Tier-1 routing surface (the description) is unchanged.
- `tests/test_release.py` pins the counter restart, cross-month/year/migration ordering, the
  `v`-prefix, and the scheme detection.
