# Product vision

## The goal in one sentence

agentic-forge is a Claude Code plugin that turns the full software lifecycle — from a
raw idea through research, product, architecture, design, planning, development, QA, and
deployment — into a set of **skills that load themselves when relevant**, where every
skill, agent, and script is held to a measurable quality bar before it ships.

## The problem

Teams adopting AI coding agents repeatedly hit the same walls:

1. **Ad-hoc prompting doesn't scale.** Knowledge lives in one person's head or in a giant
   `CLAUDE.md`. It is neither discoverable nor reusable.
2. **"Does it work?" has no answer.** Agent behavior is non-deterministic, so quality is
   judged by vibes. Regressions go unnoticed; improvements can't be proven.
3. **Workflows are invoked, not assisted.** Users must remember which command or agent to
   call. The tooling does not meet the user where their request is.
4. **Process is fragmented.** Research, product, architecture, planning, and code live in
   different tools with no shared context or knowledge base.

## The bet

Three commitments, each a direct answer to a problem above:

- **Skill-centric.** Workflows are expressed as skills that Claude auto-loads by `name`
  and `description`. The user describes their task; the right workflow arrives. Agents and
  hooks exist, but as machinery the skills drive — not things users invoke by hand.
- **Eval-driven.** No component ships without a contract and a numeric eval gate. "Working"
  is defined by thresholds, measured repeatedly, and enforced in CI. This is the core
  differentiator: agentic-forge is a *tested* agent toolkit, not a prompt collection.
- **Standard-native.** Every skill conforms to the [Agent Skills](https://agentskills.io)
  open standard and uses Claude Code primitives (subagents, plan mode, worktrees, review
  and Ralph loops) directly, so the plugin is portable in form and powerful in practice.

A self-maintained, human-readable (Obsidian) **knowledge base** in the target repo ties it
together: workflows write to it, and read from it to enrich their context over time.

## Who it is for

- **Solo builders and small teams** who want a repeatable, high-quality SDLC without a
  large platform team.
- **Engineers** who want their agent to follow the same process every time and to prove
  the process works.
- The first user is the author's own multi-project work; the design stays project-agnostic
  (operations live in the plugin; project context lives in the target repo).

## Scope

**In scope (v1 domains, second wave):**
research/brainstorm, product management, architecture/technical design, UI/UX design,
work planning, development/bugfix, QA/testing, security review, deployment/CI-CD
monitoring, code review, plus the knowledge base.

**Explicitly out of scope:**
- Multi-vendor packaging (Codex/Windsurf). Claude Code only.
- Reimplementing the eval engine — we build on `skill-creator`.
- A hosted product, UI, or backend service. This is a plugin.
- Native scheduling inside the plugin (Claude Code has none); scheduled work is delegated
  to CI/headless runs.

## What success looks like

- **Coverage:** every shipped component has an `evals/evals.json` contract and passes its
  gate. Target: 100% of components gated.
- **Quality:** Tier-2 pass-rate lower bound (mean − σ over N≥5 runs) ≥ 0.8 per skill.
- **Routing:** Tier-1 trigger recall ≥ 0.9 and specificity ≥ 0.9 — skills load when they
  should and stay quiet when they shouldn't.
- **Throughput:** a new component can go contract → green gate using `skill-factory`
  without hand-rolling structure or eval plumbing.
- **Context budget:** the always-on skill listing stays within budget (router discipline),
  so auto-loading does not degrade as the catalog grows.

## Guiding principles

State what to do and why, briefly. Prefer fewer, sharper skills over many shallow ones.
Push depth into references loaded on demand. Make scripts deterministic and tested. Keep
one source of truth per component. Recalibrate thresholds with evidence and record why.
