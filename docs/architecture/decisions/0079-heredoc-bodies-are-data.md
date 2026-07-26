# 0079 — A heredoc body is data, unless its receiver executes it

**Status:** Accepted (implemented)
**Date:** 2026-07-26
**Refines:** 0054 (rules fire on the command word of a quote-aware segment), 0075 (the remote
environment-dump rule).

## Context

A maintainer verifying 2026.7.10 in the field tried to append a section to their report with
`cat >> report.md <<'EOF' … EOF`. The security hook blocked it — because the **document being
written** contained the example commands it was documenting. The classifier matched the payload,
not an action. Nothing was being executed against any host.

Reproduced immediately here, and the reproduction is the sharpest evidence available: **the script
that reproduces it could not itself be written with a heredoc** — the same hook blocked that too.

The reporter ranked it a P3 annoyance and was explicit that they would not trade the block for it.
They are right, and the narrow consequence is still real: **you cannot write a bug report, an ADR, a
runbook or a field report about this guardrail using a heredoc** — and the people most likely to hit
it are exactly the ones documenting the incident class the rule exists to prevent.

The root cause is broader than the environment-dump rule. `_remote_env_dump` scanned the **whole
command string**, which violates this repo's own doctrine: ADR 0054 established that every rule
fires on the command word of a quote-aware segment, precisely so that a command which merely
*quotes* something dangerous never blocks. The new rule was written as a raw-text scan and
inherited none of that. That is not hypothetical: while writing the CHANGELOG entry for *this
ADR*, the sentence describing the defect tripped a **different** rule — the recursive-delete
blocker — because the entry quotes `rm -rf /` as an example. Two rules, two false positives, one
session, both on prose.

## Decision

`classify_command` strips heredoc **bodies** before classifying — unless the body's receiver will
run it:

* an **interpreter** on the opening line (`bash`, `sh`, `zsh`, `ksh`, `dash`, `python`, `python3`,
  `perl`, `ruby`, `node`, including via a pipe: `cat <<'EOF' | bash`), or
* a **remote shell** (`ssh host <<'EOF'`, `kubectl exec … <<'EOF'` — the `_REMOTE_EXEC` markers),
  where the body is a program that runs somewhere else.

`strip_heredoc_bodies` is pure, exported, and separately tested, because it is the single place a
false block (documentation) and a real bypass (`bash <<EOF`) are told apart. An unterminated
heredoc ends the scan rather than looping.

Second, the reporter's other suggestion, adopted verbatim: the block message now ends with *"If
this pattern is quoted TEXT you are writing to a file, use a file-write tool rather than a shell
heredoc."* They worked the fix out blind; nobody else should have to.

## Consequences

- **Documentation about dangerous commands stops being blocked** — for every rule, not just the
  environment dump.
- **No bypass is created.** The security question is "will something run this?", and the answer
  decides scope. Tested from both sides: `cat > doc.md <<EOF` passes, `bash <<EOF`,
  `ssh host <<EOF` and `cat <<EOF | bash` still block, and a real invocation is untouched.
- **A two-step evasion remains possible** — write a script with a heredoc, then execute it in a
  later command. That was already true before this change and is the documented limit of an
  accident-guard rather than an adversarial sandbox (`guardrails.md`).
- **The doctrine is now applied where it was skipped.** Any future raw-text rule should expect the
  same defect; the segment-and-command-word discipline exists for this reason.
