# Stage 2 — SDLC spine

Status: **Built** — the six-phase spine is implemented and proven end-to-end (Tier-3), and
by-stack ships a `*-patterns` pack for every registered language stack. Workflow model; decisions in
[ADR 0013](decisions/0013-spine-workflow-chain.md) (which supersedes the earlier "thin router"
ADR 0012). Builds on the Stage 1 engine ([engine.md](engine.md)), the handoff contract
([patterns/handoff.md](../../plugin/patterns/handoff.md)), and reuses ideas from the ancestor
`ai-skills` repo as **reference** (we build fresh to our gate, not port).

## Core idea: a chain of workflows

Each SDLC phase is **itself a workflow** — a multi-stage procedure that gathers inputs, plans,
**fans out subagents** across directions/components, synthesizes their results, and analyses
to a conclusion. The spine is a **chain of these workflows** joined only by committed handoff
artifacts in `docs/sdlc/<feature-slug>/`; it is deliberately **not** one mega-workflow (each
phase runs, lands an artifact, and the next phase consumes it). Consequence vs Stage 1:
**fan-out/fan-in is now a core, built pattern** (no longer deferred).

## Strategy: build fresh, `ai-skills` as reference

The ancestor `ai-skills` (26 agents, 77 skills, by-stack packs) already proves this shape
across runtimes. We **build fresh** to the agentic-forge gate (agentskills.io, evals.json
superset, ≤500-line bodies, Tier-0/1/2/3, Claude-only) and consult the ancestor for structure
and content. Reference map per phase below.

## The phases

| # | Skill | Workflow does (stages) | Fans out over | Reads → Writes | ai-skills ref |
| --- | --- | --- | --- | --- | --- |
| 1 | `research` | gather inputs → plan parallel tracks → fan-out → synthesize → analyse/recommend → **bounded skeptic loop** (ADR 0061) | research directions (market, product, eng, …) | request → `research-brief.md` | `analyze`, `spike` |
| 2 | `product` | digest research → assess current product → plan → user stories → define changes → PRD by template | product areas / user-story sets | `research-brief.md` → `prd.md` | `feature-design`, `product-manager` |
| 3 | `architecture` | digest PRD → study system → weigh options → component design → ADRs → risks → **bounded skeptic loop** (ADR 0060) | design decisions / subsystems | `prd.md` → `tech-design.md` + `adr-*.md` | `architecture*`, `system/solution-architect` |
| 4 | `plan` | digest design → decompose tasks → dependency order → checkpoints → deferred → validate the DAG (`plan_batches`) → **bounded skeptic loop** (ADR 0060) | work streams | `tech-design.md` → `plan.md` | `plan` |
| 5 | `develop` | pick plan step → git infra → **batch by dependency level (`plan_batches`) → fan out one worktree per independent task → integrate the level** → **multi-aspect review fan-out** (code / security / integration+API / lint) → loop-back on failure → **QA** (existing + new unit + e2e) | parallel worktrees (ADR 0034) | `plan.md` (+`tech-design`) → code in worktree(s) | `develop`, `feature-dev`, `qa`, `worktree-isolation`, `worktree-parallel` |
| 6 | `code-review` | scope the diff → fan-out reviewers by code aspect → verify → synthesize verdict → `review.md` | code review aspects | diff (+`plan.md`) → `review.md` | `code-review`, `security-audit` |

Artifact shapes are the canonical contract in
[patterns/handoff.md](../../plugin/patterns/handoff.md); not restated here.

## Specialist agent roster (expanded)

Stage 2 expands the role set beyond the Stage-1 four (this supersedes ADR 0009's "no new
roles", which was Stage-1-scoped — see ADR 0013). Per
[ADR 0014](decisions/0014-software-engineer-base-role.md): `implementer` is renamed to
**`software-engineer`** (the base engineering role), and **stack specialization lives in
skills, not per-stack agents** — `software-engineer` loads the lean `engineering-standards`
skill plus the relevant stack skill (the by-stack step) by context. New **quality
specialists** are real agents, added only as a shipping phase needs them and gated
(`component.type: agent`, Tier-2): `security-engineer` and `qa-engineer` now; others (e.g.
`sre-`/`devops-engineer`) later. Current roster: base `software-engineer`; design `architect`;
quality `reviewer`, `grader`, `security-engineer`, `qa-engineer`.

## How a phase-workflow is implemented

A shippable plugin can't depend on the harness Workflow tool, so a phase-workflow is a
**skill whose `SKILL.md` encodes the multi-stage fan-out procedure**, executed with the native
subagent mechanism (the `Task` tool) — model-driven orchestration,
the pattern agentic-forge already uses. **Deterministic glue** (stack detection, plan parsing,
artifact-header validation, synthesis scaffolding) lives in `plugin/lib/agentic_forge/` and is
unit-tested. New pattern references: **fan-out/fan-in** and **multi-aspect review**; reused:
worktree, review-loop, handoff, adversarial-review.

## Multi-language (by-stack)

The thin slice proved the workflow model on **Python**; by-stack makes the spine
stack-parametric. Mechanism (see [ADR 0015](decisions/0015-by-stack-detection-and-packs.md)):

- **Deterministic detection** — `lib/agentic_forge/stacks.py` `detect(repo)` returns ranked
  `StackProfile`s from an explicit `stack:` hint (CLAUDE.md / AGENTS.md) or manifest signatures
  (`pyproject.toml` → python, `tsconfig.json` → typescript (suppressing a co-present bare
  `package.json`), bare `package.json` → javascript,
  `go.mod` → go, `Cargo.toml` → rust, `*.tf` / `.terraform.lock.hcl` → terraform, …). Detection
  is a tested fact, not an LLM guess.
- **Hints may name several stacks** — `stack: go, java` yields one profile per named stack, in
  the hint's order; unknown names are skipped, and a hint naming none falls through to manifests.
- **Polyglot / monorepo roots** — when the root matches no manifest (and no hint), `detect` scans
  the immediate subdirectories, one level only, and returns one profile per stack and directory.
  A hinted stack with no manifest at the root is located the same way. What is bounded: every
  directory listing is one `os.scandir` cut off at 2,048 entries (the root's; each examined
  directory's, for wildcard manifests such as `*.tf`; a `tests/`; a workflows directory) — below
  the cap complete and sorted, past it whatever the filesystem returns first — and at most 64
  subdirectories are examined, in name order. An exact manifest name is one `stat`, never a
  listing. Skipped: a name that is not plain (`^[A-Za-z0-9][A-Za-z0-9._@+-]*$`, so every dot-dir
  such as `.git` / `.claude/worktrees`, and any name with whitespace, quotes or shell syntax — the
  name becomes `dir`, which a caller runs commands in), dependency or build output
  (`node_modules`, `vendor`, `target`, `build`, `dist`, `out`, `bin`, `obj`, `venv`, `env`,
  `coverage`, …), symlinked directories, and a directory this process cannot list (a bind-mounted
  `pgdata` owned by another user); a directory that fails mid-scan yields no profile instead of
  failing the repo. `scan_subdirs=False` keeps detection to the root.
- **Stack profile input** — each profile carries `stack_id`, `display`, the `pack`
  (`*-patterns` skill name or `None`), a `toolchain` (`test`/`lint`/`typecheck`/`format`
  commands), its evidence `manifests`, its `source` and the `dir` it was found in (`.` = root;
  run its commands there). Profile commands are **fallbacks** (ADR 0109): the repo's declared gate (its CI
  workflow, AGENTS.md / CLAUDE.md, Makefile, package scripts) wins. `af.py stack-detect` says so
  in its `summary` line and its `toolchain_role: "fallback"` field, and lists the files present
  where such a gate is declared in `declared_gate_sources` (root and each profile's `dir`;
  existence only, nothing is parsed or run; a path part that is not a plain name, or a file
  linking out of the repo, is left out). Those files are repo-written and untrusted: `develop`
  takes only their test, lint, typecheck and build steps.
- **Toolchains are resolved against the profile's directory**, not copied from the registry:
  - JavaScript / TypeScript: the package manager is the one the repo declares — the
    `packageManager` field (only `npm`/`yarn`/`pnpm`/`bun`; anything else is ignored, since the
    name reaches argv), then the lockfile (`yarn.lock`, `pnpm-lock.yaml`, `bun.lock`/`bun.lockb`,
    `package-lock.json`), looked for in the profile's directory and then the repo root, else
    `npm`. Each command is listed only when `package.json` declares it: the repo's script
    (`test`, `lint`, `typecheck`/`type-check`, `format`) as `<pm> run <script>`, else a declared
    (dev)dependency's binary through the manager (`npm exec --no --package=<pkg> --`,
    `yarn run`, `pnpm exec`, `bun run` — `vitest run`/`jest`, `eslint .`, `tsc --noEmit` when a
    `tsconfig.json` is there, `prettier --write .`), else `null`. None of these downloads: without
    a TTY `npm exec` assumes `--yes` and would install a missing binary from the registry (in a
    fresh worktree `npm exec -- tsc` fetches the unrelated `tsc` package), so npm always gets `--no`
    and the package the binary belongs to. `package.json` is read capped at 1 MiB, never through a
    link that leaves the repo, integers parse to 0 (Python 3.9 parses a huge one quadratically), and
    a malformed one declares nothing.
  - Go: `go test -race ./...`; lint is `golangci-lint run` when a `.golangci.{yml,yaml,toml,json}`
    sits beside `go.mod`, `go vet ./...` otherwise.
  - JVM (`pom.xml`, `build.gradle[.kts]` or `settings.gradle[.kts]`, so the `gradle init` layout
    with its build file in `app/` is found at the root): the phase that includes integration tests
    — `./mvnw verify` (Maven wrapper) or `mvn verify`; `./gradlew check` (Gradle wrapper) or
    `gradle check`. The wrapper is looked for beside the build file, then at the repo root, and
    written as a path from the profile's `dir` (`../gradlew check`). Maven wins when a directory
    has both build tools.
  - Terraform (detection only, no pack yet; specificity 0, so any language stack beside it is the
    primary): format `terraform fmt -recursive` (applies, like every stack's format), typecheck
    `terraform init -backend=false && terraform validate`, and `terraform test` only when
    `tests/*.tftest.hcl` or a root `*.tftest.hcl` exists. The typecheck is a shell command (the
    commit gate refuses any command with shell syntax, and terraform names no lint), and it is not
    read-only: `terraform init` downloads the providers and modules into `.terraform/` and may
    rewrite `.terraform.lock.hcl` — review that file in the diff.
- **The commit gate reads its own, narrower profile** (`stacks.gate_profile`): the cwd only (no
  scan, so a root with no manifest stays ungated), a hint's first name only (an unknown first name
  falls to the next hint file, then the manifests), and the hint file read wherever it links, as before multi-name hints.
  It runs a package's lint only as `npm run lint`, whatever manager the repo declares
  ([guardrails](guardrails.md)).
- **Stack reference packs** — off-listing (`disable-model-invocation: true`) `*-patterns`
  knowledge skills (toolchain, idioms, testing, layout, pitfalls), modelled on
  `engineering-standards`, read on demand by `develop` / `code-review` and the
  `software-engineer` / `qa-engineer` roles for the detected stack — **by file path**
  (`${CLAUDE_PLUGIN_ROOT}/skills/<pack>/SKILL.md`, resolved by `stacks.pack_paths`), because an
  off-listing skill cannot be invoked by name and is absent from the model's listing (ADR 0094).

**Status:** detection ships for the common stacks, and **every registered language stack ships
a `*-patterns` pack** — python, typescript, javascript, go, rust, jvm, dotnet, ruby, php.
`terraform` is the first *detection-only* stack: it falls back to `engineering-standards` + its
toolchain until a pack ships. An **unrecognized** repo (`unknown`) falls back to
`engineering-standards` only (logged, not silent).
New stacks get a pack as they are introduced.

## Trigger taxonomy

Six always-on skills must route sharply. Each owns one phase by the **artifact it produces**
(what-exists / what-&-why / how / order / make / correct). Each skill's `should_not_trigger`
set is seeded from its **neighbours'** `should_trigger` prompts, so Tier-1 **specificity**
directly measures non-overlap. The `code-review` phase routes only on SDLC-flow phrasing
("review the change from develop / record review.md for this feature"); standalone audits and
non-code review stay with `deep-review`.

## Eval model

- **Each workflow skill:** Tier-1 (trigger recall/specificity ≥ 0.9), measured on the **live
  skill listing** by `dev/run_tier1_evals.py` as the mean per-prompt routing rate over N samples
  (ADR 0016, refined by ADR 0026). A
  skill that delegates to gated roles inherits its **quality** from those roles'
  Tier-2 (≥ 0.8) rather than re-running a separate Tier-2; the end-to-end quality is the Tier-3
  scenario. A skill with substantial own logic still ships a `tier2_quality` gate.
- **Each new specialist role:** Tier-2 via the agent eval runner.
- **The spine:** Tier-3 E2E on a **fixture target-repo** (Python), one feature through the
  phases in an isolated copy/worktree, with per-phase checkpoints (artifact exists + validates;
  PRD goals trace to design; plan covers design; develop's code passes the repo's tests;
  code-review returns a verdict).

## Thin slice first

Build order (your choice): **`architecture → develop → code-review`** as workflows, on the
Python fixture repo. `develop` is the flagship (git infra → implement the step in a single
worktree → multi-aspect review fan-out → QA) and exercises the riskiest machinery. Minimum new
roles for the slice: `security-engineer` and `qa-engineer` (review + QA); implementation uses
<!-- develop now batches independent plan tasks across parallel worktrees (ADR 0034); the single-worktree slice above is the original thin-slice narrative. -->
the renamed `software-engineer` (was `implementer`). Stack engineers stay deferred to the
by-stack step. Prove the slice end to end, record Tier-1/2/3, then add
`research`, `product`, `plan`, and the by-stack mechanism.

## Exit criteria

- Six workflow skills: Tier-1 ≥ 0.9 recall/specificity; quality via the delegated roles'
  Tier-2 (≥ 0.8) and the Tier-3 scenario.
- New specialist roles each pass Tier-2.
- Fan-out/fan-in + multi-aspect-review patterns documented and used.
- Tier-3 E2E green on the fixture repo with all phase checkpoints.
- Tier-0 green throughout; docs + CHANGELOG updated per change.

## Implementation tasks

1. ~~Patterns: `fan-out-fan-in.md`, `multi-aspect-review.md`. Fixture Python target-repo.~~ Done.
2. ~~Thin-slice roles (evals-first): `software-engineer`, `security-engineer`, `qa-engineer`.~~
   Done (stack engineers deferred to by-stack — ADR 0014).
3. ~~Thin-slice workflows (evals-first): `architecture`, `develop`, `code-review`.~~ Done.
4. ~~Tier-3 scenario runner for the slice; prove end to end.~~ Done (Tier-3 PASS).
5. ~~Complete spine: `research`, `product`, `plan`.~~ Done — all six phase skills built + gated.
6. ~~Extend the Tier-3 scenario to all six phases.~~ Done — full six-phase E2E proven.
7. ~~The by-stack mechanism + non-Python stacks.~~ Done — a `*-patterns` pack for every
   registered stack (ADR 0015).
8. ~~A real Tier-1 runner on live skill descriptions.~~ Done — `dev/run_tier1_evals.py` /
   `lib/agentic_forge/tier1_runner.py` (ADR 0016); scored as the mean per-prompt routing rate
   (ADR 0026), replacing the earlier ad-hoc router sim.
9. ~~An automated skill-Tier-2 CLI.~~ Done — `dev/run_skill_evals.py` /
   `lib/agentic_forge/skill_eval.py` (ADR 0017): knowledge skills run as the software-engineer
   with them loaded, deep-review/skill-factory directly; graded + gated like agent Tier-2.
   (`skill-factory` is resolved from the maintainer root `.claude/skills` since ADR 0105.)
10. ~~Layer 3 (knowledge base).~~ Done — vault + `knowledge` skill + session-start hook (ADR 0018).
11. ~~Layer 4 (guardrail hooks).~~ Done (ADR 0019). Remaining optional: with/without-skill delta
    for marginal-lift.

## Defaults to confirm or override

- Names: `research, product, architecture, plan, develop, code-review` (the last kept as a
  compound, code-specific, to avoid the `review`/`deep-review` collision).
- Phase-workflows are model-driven fan-out (SKILL.md procedure + `lib/` glue), not the harness
  Workflow tool.
- Thin slice `architecture → develop → code-review` on a Python fixture repo; by-stack later.
