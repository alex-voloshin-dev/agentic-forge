# Security Policy

agentic-forge is a Claude Code plugin — a set of skills, subagents, hooks, and Python
library code. It ships no network service and no deployable artifact, so its security
surface is the **plugin code that runs inside a contributor's Claude Code session**: the
guardrail hooks, the shared `lib/`, and the dev CLIs.

## Reporting a vulnerability

**Do not open a public issue for a security report.**

Use GitHub's private reporting instead: **Security → Advisories → Report a vulnerability**
on this repository ([Privately reporting a security
vulnerability](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)).
If that is unavailable, email **alex@voloshin.net** with `SECURITY` in the subject.

Please include:

- the affected component (hook / lib module / CLI) and version or commit,
- a description of the issue and its impact,
- minimal steps or a proof of concept to reproduce.

You will get an acknowledgement within **7 days**. We will confirm the issue, agree on a
disclosure timeline, fix it, and credit you in the release notes unless you prefer to stay
anonymous. Please give us a reasonable window to ship a fix before any public disclosure.

## What is in scope

- The guardrail hooks (`plugin/hooks/`) — e.g. a deny-list bypass, a secret reaching the
  audit log unredacted, or a hook that fails in a way that weakens the session.
- The shared library (`plugin/lib/agentic_forge/`) and the dev CLIs (`dev/`) — e.g. unsafe
  command construction, path traversal, or unsafe handling of untrusted input.
- The provider seams (`connectors.py`, `external_review.py`, `pr_watch.py`) — e.g. a
  command-injection vector through an injected seam.

## What is out of scope

- Vulnerabilities in Claude Code itself, or in the Anthropic API — report those to Anthropic.
- Vulnerabilities in third-party dependencies — report upstream (we will bump once a fix is
  released).
- A model "saying something it shouldn't": agentic-forge orchestrates Claude; model-level
  safety is Anthropic's surface, not this plugin's.

## A note on the guardrails

The L4 hooks (security deny-list, test-gate, budgets) are **defence-in-depth, not a sandbox**.
They block clearly-dangerous commands and fail *open* by design (a guardrail bug must never
break a session — ADR 0019). Do not rely on them as your only protection when running an agent
against an untrusted repository.
