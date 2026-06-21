---
name: engineering-standards
description: The engineering standards agentic-forge always applies when writing code in a target repo — change discipline, test discipline, a security baseline, and conventions. Loaded by the software-engineer base role (and reusable by reviewers/QA); kept off the always-on listing.
disable-model-invocation: true
---

# Engineering standards

The standards we hold to when implementing in a target repo. This is deliberately short — it
lists only what is project-opinionated or easy to skip, not general programming knowledge the
model already has. Load the matching **stack skill** (e.g. a `*-patterns` skill) for
language/framework idioms.

## Always

- **Fit the repo.** Read neighbouring code first; mirror its conventions, naming, structure,
  and error style. Do not impose a new style or framework.
- **Small, scoped changes.** Do exactly the task; surface unrelated issues as follow-ups
  rather than fixing them inline. State any assumption you had to make.
- **Tests ship with behaviour.** Every behaviour change adds or updates tests, including the
  boundary/error cases. Never weaken, skip, or delete a test to make the suite pass — fix the
  code.
- **Fail loudly.** Handle errors or propagate them with context; no silent excepts, no
  swallowed failures.
- **Security baseline.** Validate input at trust boundaries; parameterised queries (never
  string-built SQL/commands); no secrets in code or logs; safe defaults; least privilege.
- **Dependencies are a cost.** Prefer the standard library and what the repo already uses;
  justify any new dependency.
- **Leave the gate green.** Match the repo's lint/type/test gate before handing off.

## Don't

- Don't restate or re-derive well-known concepts in code comments or output — be concise.
- Don't touch the main checkout; work in the provided worktree.
- Don't broaden scope, change public contracts, or reformat untouched code without reason.
