---
type: review
feature: agentic-forge-2026.11.12
iteration: 3
verdict: changes
---

# Review round 3: the commit gate follows the commit's directory (item 7, ADR 0111)

Diff: branch `fix/commit-gate-cwd` (23e54db, d27da4f, 8679edc) against master 7b014d6.
Lenses: reviewer (approve), security-engineer (approve), external lens codex (changes).
Aggregated verdict: changes (one verified major). Decision: escalate (budget N = 3 exhausted).
Escalated to the owner on 2026-11-13; the owner chose: fix, one more review round, then release.

All eight round-2 findings are resolved (reviewer checked each against the source).

## Findings (verified against the source)

### Major
1. **The tracked-content check reads the target as a pathspec glob** (codex major; reviewer and
   security minor). `git ls-files --error-unmatch -- <target>` matches `*`, `?` and `[` as
   wildcards (verified in the worktree: `plugin/hoo*` lists `plugin/hooks/...`). An untracked,
   unignored directory with such a name passes when a tracked sibling fits the pattern, and the gate
   would run its scripts before the permission prompt. Bounded to the start directory's own work
   tree. Fix: match literally on this call only (`--literal-pathspecs` or `:(literal)`), not in the
   shared `_GIT` flags (check-ignore may refuse it); add an untracked `x*` beside a tracked `xa/f`.

### Nit
2. `isdir`/`realpath` run outside the 2 s budget; state it in ADR 0111 Limits (reviewer, security).
3. `docs/architecture/guardrails.md:185` overlong line (reviewer).
4. `guardrails.py:1474` section comment still says only "not ignored" (reviewer).
5. The hint's `shlex.quote` branch is untested; add a path with a space (reviewer).
