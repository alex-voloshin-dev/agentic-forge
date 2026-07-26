# 0071 — Review artifacts: index by iteration, one per round, cleaned on success

Status: Accepted — **implemented**. Corrects the persistence instruction added by
[0067](0067-deep-review-remediation.md) §7 and specifies the contract
[review-loop.md](../../../plugin/patterns/review-loop.md) had left implicit.

## Context

**Field report, not a gate finding:** a live `architecture` run left several review files behind,
with different contents, and removed none of them. Every gate was green — this is behaviour of
model-followed instructions, which no unit test observes.

Reading the instruction ADR 0067 §7 shipped, the cause is in the specification, in three parts:

1. **The filename could not satisfy its own requirement.** The instruction said *"Persist each round
   — write `docs/sdlc/<slug>/review-<artifact>.md`"*: one fixed name, written every round, with the
   round number only in the frontmatter. But `review-loop.md` requires the history to be *auditable*.
   A fixed name overwrites, so the two asks are incompatible — and a writer honouring auditability
   has no choice but to invent a naming convention. It did.

2. **Two lenses per round, with no rule about where each goes.** Every round runs the internal
   `reviewer` **and** the external one, and the instruction even suggested
   `dev/external_review.py --out … --iteration N`, which invites a *separate* file for the external
   lens. Nothing said whether to aggregate. So the count multiplies by lenses as well as rounds —
   which matches the report's "several files with different reviews".

3. **No lifecycle at all.** Nothing said when a review artifact stops being useful. Partly by
   design — ADR 0040's non-convergence scan reads `docs/sdlc/**/review*.md`, so the files are meant
   to outlive the run — but that reasoning only holds for a loop that **failed**. On a converged
   loop the intermediate rounds gate nothing and the scan can never flag them, so they are litter in
   a user's repository.

## Decision

The contract lives in `review-loop.md` (one place for all seven loops), and each skill body points
at it:

1. **The iteration goes in the filename**: `review-<artifact>-<iteration>.md`. Deterministic, so the
   writer invents nothing, and the history is genuinely preserved rather than overwritten.
2. **One artifact per round, aggregating every lens.** The internal and external verdicts are
   already aggregated into the single verdict `review_loop_decision` consumes; their findings belong
   in one file for the same reason. A file per lens multiplies output for no gain.
3. **Lifecycle by exit:** on `escalate` **keep every round** — they are the evidence for the
   unresolved findings and the input the ADR 0040 scan needs. On `proceed` keep only the **final**
   round (the one recording the `approve`) and delete the earlier ones.

`diagnostics.REVIEW_GLOB` (`docs/sdlc/**/review*.md`) already matches the indexed names — verified,
no change needed.

## Alternatives considered

- **Keep one fixed filename and drop the auditability requirement.** Rejected: the per-round history
  is what makes a non-converged loop diagnosable, and ADR 0040's scan is built on it.
- **Keep every round on `proceed` too (full audit).** Defensible — a complete review trail has value
  — but rejected as the default: it hands a user files they did not ask for, gates nothing, and this
  ADR exists precisely because that happened. A repo wanting the full trail can keep them; the rule
  is stated in one place and easy to change.
- **A separate file per lens.** Rejected — it is the second multiplier behind the report, and the
  verdict the loop acts on is already aggregated.

## Consequences

- A converged loop now leaves exactly one review artifact per artifact reviewed; an escalated one
  leaves the whole trail, which is the case where the trail is worth having.
- `test_review_loop_shape.py` pins the indexed name and the cleanup clause across all seven loops,
  so this specification cannot silently drift — the same guard added for the review and delivery
  contracts, both of which had shipped broken before.
- The instruction is now ~4 lines per skill instead of ~4 sentences, with the reasoning in the
  pattern. Bodies shrank; the router budget is untouched (no `description` changed).
- **Unobserved by any gate.** This class — instructions a model follows into a mess — is only caught
  by running the phase and looking at the tree. The field report was the detector; there is no
  automated substitute in the pyramid today.
