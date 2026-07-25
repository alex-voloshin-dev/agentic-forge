---
type: release
feature: agentic-forge-2026.7.1
status: final
version: 2026.7.1
date: 2026-07-14
changelog:
  - "Fixed: security deny-list fires on the command word of a quote-aware, shlex-tokenized segment — quoted mentions of dangerous strings (commit messages, grep/sed patterns, python -c scripts) no longer block; sh -c payloads and command substitutions still classify recursively (ADR 0054)"
  - "Fixed: diagnostics bundle ships the plugin manifest + version (read from the plugin root; installed_plugins.json with legacy fallback) and discloses the legacy audit share instead of overclaiming valid JSON (ADR 0052/0053 follow-up)"
  - "Fixed: models.py imports on Python 3.9 (missing future-import) + new Tier-0 validate_python_compat gate over every shipped runtime .py (ADR 0050 upheld)"
  - "Fixed: commit-gate infra fail-open now emits a diagnostics anomaly event (ADR 0039 upheld)"
  - "Changed: CalVer versioning <year>.<month>.<inc> — this is the first release under the scheme (ADR 0055)"
  - "Changed: config.example.json ships a neutral models key; configuration.md documents what models affects and the user-vs-developer Python baseline"
  - "Added: field-driven product plan in docs/roadmap.md (pr-watch skill, deploy-watch k8s coverage, deep-review workflow assets, observability hygiene)"
breaking: []
---

# Release 2026.7.1

The first CalVer release (ADR 0055): `<year>.<month>.<inc>`, month counter restarting each
month; the version now dates the install. Everything in this cut comes out of the second
production diagnostics bundle (an anonymised downstream repo, 7 days / 136 sessions / 5,541 tool
calls, plugin 0.0.1→0.1.0 mid-window) and this repo's own diagnostics log.

## Scope

One work commit since `v0.1.0` (`6571e71`), carrying ADR 0054 (command-position deny-list) and
ADR 0055 (CalVer) plus the diagnostics-bundle, py3.9, commit-gate, and config-UX fixes, and the
field-driven roadmap plan. Curated entries live in `CHANGELOG.md` under `[2026.7.1]`; the groups
above mirror them. No breaking changes.

## Verification

- Tier-0 `dev/validate.py`: OK (includes the new `validate_python_compat` gate).
- `pytest`: green, coverage 96.7% (threshold 80%).
- `ruff` / `mypy` (CI scope): clean.
- Live checks: the security hook re-tested under `/usr/bin/python3` 3.9.6 (field baseline) on the
  production false-positive corpus and true hazards; a real bundle built under 3.9 ships
  `plugin-meta/plugin.json`, `installed_plugins.json`, the `plugin:` line in `environment.txt`,
  and the legacy-share disclosure.

## Tag

`v2026.7.1` (annotated), matching the `v0.1.0` naming convention. History is append-only — no
rewrites; pre-migration semver tags stay.
