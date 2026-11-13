---
type: review
feature: agentic-forge-2026.11.12
iteration: 2
verdict: changes
---

# Review round 2: the commit gate follows the commit's directory (item 7, ADR 0111)

Diff: branch `fix/commit-gate-cwd` (23e54db, d27da4f) against master 7b014d6.
Lenses: reviewer (approve), security-engineer (approve), external lens codex (changes).
Aggregated verdict: changes (one verified major). Decision: revise.

All twelve round-1 findings are resolved (reviewer checked each against the source; #9 is a
documented limit). The gate only ever runs in a directory inside the start directory's own work
tree, so every remaining finding is a wrong directory within that work tree, not an escape.

## Findings (verified against the source)

### Major
1. **`CDPATH` exemption too wide** (codex major, reviewer minor). With `CDPATH` set, bash and zsh
   search it for `.github`; only `/…`, `.`, `./…`, `..` and `../…` are exempt. Fix: exempt only those
   forms; add a `cd .hidden` regression.

### Minor
2. **`-C` through a missing intermediate directory** (codex). `-C missing/../x` is normalised
   without checking each step exists; git refuses it. Fix: check the joined path exists before
   `realpath`, per step; `-C ''` stays a no-op.
3. **Untracked, unignored content is accepted** (security). An extracted archive or a clone with its
   `.git` removed inside the work tree becomes the gate's directory. Fix: require tracked content
   under the target (`git ls-files --error-unmatch`), same hardening and budget.
4. **`check-ignore` without `--no-index`** (security). An ignored directory with one tracked file is
   reported not ignored. Fix: `--no-index`; add an ignored `dist/` with a tracked `.gitkeep` test.
5. **Block hint for a moved commit** (reviewer). The hint advises a bare `git commit`, which runs in
   the start directory under a different gate. Fix: when the directory moved, name it
   (`cd <dir>` in one call, then `git commit`) or drop the hint; assert it.

### Nit
6. Check containment (target's real path at or under the start's real top) before running git in the
   target; filesystem calls outside the budget (security).
7. ADR 0111 names `gate_decision`; the logic is in `decide`/`_gate` (reviewer).
8. Limits: physical `cd` shell options (`set -P`, `CHASE_LINKS`, `CHASE_DOTS`); the hook sees only
   its own environment's `CDPATH` (reviewer).
