# 0003 — Eval-driven, contract-first, four-tier pyramid

Status: Accepted

## Context

Agent output is non-deterministic; "it seemed to work" is not a quality bar. We want every
component to have a measurable definition of done, set before implementation.

## Decision

Adopt contract-first, evals-first development with a four-tier pyramid:

- Tier 0 static (always blocks): validation, `pytest`, `ruff`, `mypy`, coverage.
- Tier 1 trigger: recall ≥ 0.9, specificity ≥ 0.9.
- Tier 2 quality: LLM judge, N ≥ 5, pass-rate lower bound (mean − σ) ≥ 0.8, overhead budget.
- Tier 3 E2E: workflow scenarios with checkpoints.

Thresholds are starting points, recalibrated with recorded rationale. Cheap deterministic
gates run always; expensive LLM gates run on changed components / cost-gated CI.

## Alternatives considered

- **Single LLM pass-rate number.** Rejected: noisy and misleading without multiple runs.
- **Max rigor everywhere from day one.** Rejected: too slow/expensive; the pyramid lets
  cheap checks catch most issues first.
- **No formal evals (smoke only).** Rejected: defeats the core differentiator.

## Consequences

- Building a component costs more up front (write evals first) but yields provable quality
  and regression protection.
- Requires harness infrastructure (ADR 0005) and a contract format (ADR 0006).
- Gating on the lower bound, not the mean, is deliberate noise absorption.
