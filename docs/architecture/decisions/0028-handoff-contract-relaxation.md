# 0028 — Relax the handoff header contract: open `status`, string-or-object list entries

Status: Accepted (relaxes [ADR 0010](0010-handoff-schemas-and-pattern-references.md))

## Context

[ADR 0010](0010-handoff-schemas-and-pattern-references.md) pinned the handoff header schemas
in `handoff.py` and deliberately constrained three small vocabularies and the list shapes:
feature `status` was a closed enum (`draft|in-review|approved|final|superseded`), and the
primary domain lists took bare-string items. It also warned that changing those is a breaking
change for any consumer that branches on them.

Building Stages 2–6 produced many real artifacts, and two of those constraints turned out to
reject legitimate output rather than catch bugs:

- **`status`** — real phase artifacts use lifecycle labels well beyond the five enum values
  (`complete`, `ready`, `shipped`, `mitigating`, `blocked`, …). The closed enum failed valid
  artifacts and pushed authors to contort their wording, while no consumer actually depended
  on the closed set (downstream phases branch loosely — "is it approved-ish").
- **List entries** — a decision / component / risk / source is often richer than a string: a
  decision is `{id, title, adr}`, a component is `{name, change}`, a risk is
  `{risk, mitigation}`. Forcing bare strings either lost that structure or buried it in prose
  the next phase couldn't parse.

`verdict` (`approve|changes`) and finding `severity` (`blocker|major|minor|nit`), by
contrast, *are* branched on directly (the review loop early-exits on `approve`; aggregation
keys off `severity`) and their vocabularies are small and stable — so those should stay closed.

## Decision

Relax two parts of the ADR 0010 contract, and keep the rest:

- **`status` becomes any non-empty string.** The five-value list survives as the documented
  **recommended** vocabulary (`STATUSES` in `handoff.py`, with a comment that it is guidance,
  not enforced); the schema requires only `minLength: 1`. Consumers map liberally.
- **List entries accept string *or* object** (`_ENTRY = {"type": ["string", "object"]}`).
  The required-vs-optional rules from ADR 0010 are unchanged (identity + primary lists
  required, secondary lists type-checked when present); only the *item* type widened.
- **`verdict` and `severity` stay closed enums**, and `additionalProperties: true` remains so
  artifacts may still carry extra fields.

## Alternatives considered

- **Keep the closed `status` enum, just expand it to the observed labels:** rejected —
  lifecycle labels are open-ended and project-specific; we'd chase the set forever, and no
  consumer needs the closure. Guidance + free-form is the honest contract.
- **Allow only strings, push structure into the body:** rejected — the next phase parses the
  header, not the prose; structured entries are exactly what makes a handoff machine-readable.
- **Relax `verdict`/`severity` too, for symmetry:** rejected — those are genuinely branched
  on and small; closure is load-bearing there, not incidental.

## Consequences

- Artifacts that were valid-in-spirit but rejected by the old enum/string rules now validate;
  malformed artifacts still fail fast (missing identity fields, wrong types, a non-string
  `status`, a bad `verdict`/`severity`).
- ADR 0010's "changing the status vocabulary is breaking" note is superseded **for `status`
  and list-item shape specifically**; `verdict`/`severity` remain part of the frozen contract.
- `handoff.py` documents `STATUSES` as recommended-not-enforced, so the guidance survives for
  authors without rejecting valid variety. `tests/test_handoff.py` covers a free-string status
  (`test_status_accepts_free_string`), a rejected non-string status (`test_bad_status_type`),
  and mixed string/object list entries.
