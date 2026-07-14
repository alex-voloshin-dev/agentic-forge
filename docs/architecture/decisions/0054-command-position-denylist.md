# 0054 — Deny-list rules fire on the command word of a quote-aware segment

Status: Accepted — implemented (see the [Unreleased] CHANGELOG entry).

## Context

ADR 0051 fixed the "network download into a shell" rule so it only fires when `curl`/`wget` is in
**command position** — but the other deny-list rules (`rm`, `chmod`, `find -delete`, force-push,
mkfs/dd) kept the old text-match design: a regex over the raw segment text, with quotes *stripped*
so quoted targets (`rm -rf "/"`) are seen. Two mechanisms made **data look like code**:

1. Segmentation split on `;`/`|`/`&`/newline **inside quoted strings**, so a Python/regex literal
   like `r'push --force|rm -rf /|reset --hard'` became three "segments", one of which begins
   `rm -rf /`.
2. Quote-stripping then erased the only evidence that the text was data.

The next production diagnostics bundle (7 days, 136 sessions) plus this repo's own diagnostics
log showed the class recurring after 0051 — four `block` events, every one a false positive:
`python3 -c` analysis scripts, a heredoc, and a grep pattern that merely *mention* `rm -rf /` or
`curl … | sh`. A synthetic probe confirmed 6 of 8 representative "dangerous string as data"
commands blocked (`git commit -m "block rm -rf /"`, `grep "rm -rf /" docs/`, `echo`, `sed`).
The guard's contract (ADR 0019: conservative accident-guard, "only unambiguous hazards match")
makes these bugs, not trade-offs.

## Decision

Extend the command-position principle to the whole deny-list (`guardrails.py`):

1. **Quote-aware segmentation** — `_split_segments` splits on `;`/`|`/`&`/newline **outside
   quotes** only. If a quote is left open (prose apostrophe, truncated input), the naive split is
   unioned in, so an unparseable tail can never *mask* a hazard (block-leaning degradation).
2. **Tokenization** — each segment is tokenized with `shlex` (quotes stripped per-token, so
   `rm -rf "/"` still shows target `/`, while a quoted phrase stays ONE token that can never
   fullmatch a flag or path).
3. **Command-position rules** — each rule fires only when its command is the segment's command
   word after `sudo`/env-assignment/wrapper prefixes (`env`, `timeout 5`, `nice`, …): `rm`
   (recursive+force+dangerous target), `chmod` (recursive+permissive+dangerous target), `find`
   (`-delete` + bare root/system start path), `mkfs*`/`dd` (a `/dev/` argument), `git`
   (subcommand `push` + force + protected destination — so a commit *message* mentioning
   "push --force main" can never fire).
4. **Executable payloads are still followed** — a sh-family `-c` argument and `$(…)`/backtick
   substitutions are re-classified recursively (depth-capped), so `bash -c "rm -rf /"` and
   `echo $(rm -rf /)` still block.
5. **Legacy fallback** — a segment `shlex` cannot tokenize degrades to the pre-0054 text checks
   (block-leaning) rather than silently passing.

The raw-text blockers stay only where quoting-as-data is implausible: the fork bomb glyphs and a
redirect into a raw disk device.

## Alternatives considered

- **Anchor each regex to segment start (0051-style) without tokenizing:** rejected — the false
  positives came from *segmentation inside quotes*, so anchoring alone still fires on
  `…|rm -rf /|…` inside a string literal.
- **Full shell parsing (bashlex or similar):** rejected — a third-party dependency on the
  stdlib-only hook path (ADR 0050), and heredoc/expansion fidelity is not needed for an
  accident-guard.
- **Keep text-match and whitelist known-safe wrappers (`python3 -c`, `git commit -m`, `grep`):**
  rejected — an open-ended enumeration that re-grows with every new tool; command-position is one
  principle that covers them all.

## Consequences

- Commands that *mention* dangerous strings (commit messages, grep/sed patterns, `python3 -c`
  analysis scripts, docs examples) no longer block; every previously-blocked true hazard still
  blocks, now including wrapper-prefixed (`timeout 5 rm -rf /`) and path-qualified (`/bin/rm`)
  forms the old text-match missed or matched by accident.
- Known limitation (documented trade-off): a wrapper flag that takes a separate argument
  (`sudo -u root rm -rf /`) can mask the command word, and remote execution (`ssh host 'rm …'`)
  is out of scope — both deliberate/rare shapes, not accidents; the old design over-matched far
  more than it covered here.
- `tests/test_guardrails.py` gains the production false-positive corpus as allow-cases and the
  payload/wrapper true positives as block-cases; documented in `docs/architecture/guardrails.md`.
- Upholds ADR 0019's contract and completes the command-position refinement started by ADR 0051.
