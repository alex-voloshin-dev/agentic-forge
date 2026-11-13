---
type: review
feature: agentic-forge-2026.11.12
iteration: 4
verdict: changes
---

# Review round 4 (owner-approved extra round): the commit gate follows the commit's directory

Diff: branch `fix/commit-gate-cwd` (through 757a8f6) against master 7b014d6.
Lenses: reviewer (approve), security-engineer (approve, one minor), external lens codex (changes).
Aggregated verdict: changes. The round-3 glob bypass is closed (all three lenses).

## Findings (verified in a scratch repository)

### Major
1. **The tracked check accepts an index entry that is the target itself** (codex major, security
   minor). `ls-files --error-unmatch -- <target>` exits 0 for (a) a tracked file replaced on disk,
   unstaged, by a directory, and (b) an uninitialised submodule directory (gitlink, mode 160000)
   later filled with content; from inside it `rev-parse` reports the parent's work tree. A trailing
   slash fixes (a) but not (b). Fix: list `ls-files -z -s -- <target>/` literally and require a
   regular (non-gitlink) entry strictly beneath the target.

### Nit
2. ADR 0111 Limits misstates what runs outside the budget (reviewer).
3. `docs/architecture/guardrails.md` ragged wrap near line 54 (reviewer).

## Disposition
The fix is narrow (one read and its parsing). It is verified by a focused re-check of the delta by
the security lens and the external lens, plus the full gate and QA, as the owner's "one more check,
then release" decision covers.
