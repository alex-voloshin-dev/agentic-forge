# Stage 2 — SDLC spine

Status: **Built** — the six-phase spine is implemented and proven end-to-end (Tier-3), and
by-stack ships a `*-patterns` pack for every registered stack. Workflow model; decisions in
[ADR 0013](decisions/0013-spine-workflow-chain.md) (which supersedes the earlier "thin router"
ADR 0012). Builds on the Stage 1 engine ([engine.md](engine.md)), the handoff contract
([patterns/handoff.md](../../plugin/patterns/handoff.md)), and reuses ideas from the ancestor
`ai-skills` repo as **reference** (we build fresh to our gate, not port).

## Core idea: a chain of workflows

Each SDLC phase is **itself a workflow** — a multi-stage procedure that gathers inputs, plans,
**fans out subagents** across directions/components, synthesizes their results, and analyses
to a conclusion. The spine is a **chain of these workflows** joined only by committed handoff
artifacts in the feature's folder (`docs/sdlc/<feature-slug>/`, or the repository's own when it
keeps one); it is deliberately **not** one mega-workflow (each
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

## The review phase on a pull request

Since ADR 0110: the widened concurrent-change step and `af.py pr-review`.

Two parts of `code-review` exist because of what a pull request adds to a diff.

**A tightened contract breaks consumers in other PRs.** The concurrent-change aspect (ADR 0074)
used to fire only on a claim, lock, lease, dedup guard or status transition. A field case showed
the same failure with any contract: PR A made a Terraform module input required in production
(a validation and preconditions), and PR B, merged first, added a test that planned production
without it. Each was green alone; after A merged the module test went red, and since that check
was not required GitHub showed the PR as UNSTABLE, which does not block a merge. So the aspect now
fires on any contract the diff tightens: a new required input, parameter or field, a stricter
validation, a changed signature, schema or return type, a removed default, as well as the state
transitions it already covered. For such a diff the session, not a lens (the `role_scope` hook
keeps `gh`, worktrees and tests from the lens roles; a lens may run the `git grep`), (1) looks for
the contract's consumers in the base (`git grep` at `origin/<base>`) and in open PRs:
`gh pr list --state open --limit 21`, keeping those with the same `baseRefName` and skipping the
PR under review, then each one's `gh pr diff`. Twenty is the bound, and a 21st answer is how it
knows to say more were open than were searched. (2) After `git fetch origin <base> pull/<n>/head`,
`git merge-base --is-ancestor origin/<base> <sha>` exiting 1 says the base moved since the head was
cut, so the PR's CI never saw the current base; it then reviews a head that contains the current
base, or runs the affected tests on a trial merge in a scratch worktree at `<sha>` (merge
`origin/<base>` with `--no-commit --no-ff`, run, abort, remove). A consumer that would break is a
finding on the tightening diff. The `deep-review` lens catalog carries the same trigger. It stays
instruction-level, as ADR 0074 is: nothing enforces the search.

**The reviewed head is recorded first.** For a PR, step 1 reads `headRefOid` and `baseRefName`
(`gh pr view <n> --json headRefOid,baseRefName`) before anything else, fetches
`origin <base> pull/<n>/head`, and reviews `git diff origin/<base>...<sha>`, a commit rather than
the branch. Step 5 passes that same `<sha>` to `pr-review`, never a fresh lookup: a fresh one would
make the re-check below compare the PR against a head nobody reviewed, and pass.

**Posting the review: `af.py pr-review`.** For a PR target the review goes to GitHub instead of
`review.md` (still the output for a local diff and the spine). The session writes the findings, in
the review-finding shape of [patterns/handoff.md](../../plugin/patterns/handoff.md), to a JSON file
and runs:

```bash
python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" pr-review --repo . --pr <n> --head <sha> \
  --findings-json <file> --out <payload-file> [--event request-changes|comment|approve]
```

What it does, in order:

1. Validates the findings (`pr_review.parse_findings`): an array, or an object with `findings`
   and optionally `verdict` and `summary`; each finding needs `severity` (`blocker`, `major`,
   `minor`, `nit`), `location`, `issue` (or `description`) and `suggestion` (or `fix`); `evidence`
   is optional; at most 200. With no `verdict` it is derived (any blocker or major is `changes`),
   and a given `approve` over a blocker or major is refused. `--head` must be a full commit id.
   All this happens before `gh` is asked anything.
2. Resolves `owner/name` from the checkout's `origin` (`connectors.remote_slug`), then reads the
   PR's state, head and author, and the asking account, in one read-only `gh api graphql` call
   (owner and name as strings, `-f`, so a repository named `2048` or `null` stays a string);
   reads the diff with `gh pr diff`; and reads the state and head again. Each `gh` read has the
   60-second bound of every `af.py` read. A PR that is not open, or a head that is not `--head`
   at either read, is refused: a push between the review and the post would otherwise put the
   verdict on a commit nobody reviewed, and the diff read in between is then the reviewed head's.
3. Parses the diff's hunks by their line counts (`commentable_lines`) for the RIGHT-side lines a
   comment may sit on: added and context lines; a renamed file by its new name; nothing for a
   deleted file or a hunk-less rename. A finding whose `file:line` or `file:start-end` is on those
   lines becomes an inline comment; any other goes into the body with the reason. A finding's path
   may also be a unique `/`-bounded suffix of a diff path (`app.py:3` for `src/app.py`), or end
   with one (an absolute path, or git's `a/`/`b/`). GitHub answers a review holding one comment
   outside the diff with a 422 and drops all of it. The diff is read as bytes and decoded as UTF-8
   without newline translation: a lone `\r` in a line is content to git and GitHub, and reading it
   as a line break would shift every later line number.
4. Renders each finding as severity, `file:line`, the issue, the fix and the evidence, and
   neutralises all of the text: a zero-width space after every `@` not right after an ASCII letter
   or digit (an email address is left alone), `@` written as `&#64;`, `&#x40;` or `&commat;` (any
   case) turned into the same, and a `<` at the start of a line, after any blockquote or list
   markers, escaped as `\<`, so that `<!--`, `<pre` or `<script` cannot open an HTML block that
   hides the findings after it. Code is not exempt. An earlier version left code spans and fences
   alone, and review showed it bypassable: a list item or a blockquote on the next line cuts a code
   span, a container ends a fence, an autolink or a tag beats a backtick, a table cell splits on
   `|`. Each of those notified a real person, where a zero-width space in a code sample costs one
   character. Each comment is capped at 8,000 characters and the body at 60,000; the body opens
   with the verdict, the counts and the reviewed commit, and a finding it has no room for is
   counted in `omitted` and placed as `omitted: body cap`.
5. Maps the verdict to an event. `request-changes`, the default, sends REQUEST_CHANGES for
   `changes` and COMMENT for `approve`; `comment` sends COMMENT for both; `approve` sends APPROVE
   and is refused on a `changes` verdict. An approval is never the default: an APPROVE from the
   session's account counts toward the approvals branch protection requires, so it could open the
   merge gate on a model's judgement. On the asking account's own PR, where GitHub refuses both
   APPROVE and REQUEST_CHANGES, the event is COMMENT, and the body says why.
6. Writes the payload (`commit_id`, `event`, `body`, `comments[]` with `path`, `line`,
   `side: RIGHT` and, for a range, `start_line`) to `--out`, and prints
   one JSON object: `repo`, `number`, `head`, `verdict`, `event`, `event_reason`, the `inline`,
   `in_body` and `omitted` counts, a `placements` entry per finding, `payload`, and `post`, the
   `{"argv", "shell"}` of `gh api -X POST repos/<owner>/<name>/pulls/<n>/reviews --input <payload>`.
   `--out` must be under the repository (`--repo`) or the temp directory (`$TMPDIR`, else the
   system's: Python's `tempfile.gettempdir()`), each as written and as it resolves, and no
   component below that root may be a symlink (`state_io`, with the root as the anchor). Checking
   only the file's own directory let a linked directory higher up carry the write elsewhere.
   The path must end in `.json`, and under the repository no component of it may start with `.`.
   A write keeps an existing file's mode, so without that a payload, JSON whose strings carry PR
   text such as `$(...)`, could replace `.git/hooks/pre-commit` and stay executable, or land in
   `.husky` or `.github`, which run elsewhere. This holds even for a repository inside the temp
   directory.

It posts nothing itself. Posting is outward-facing, so the session runs `post.shell`, where the
guardrail hooks see it (ADR 0104, decision 4). Exit codes are `af.py`'s: 0 built; 1 refused
(malformed findings, a head that moved, a closed or merged PR, no GitHub `origin`, a `gh` that
failed, is missing or answered something unreadable, a diff over 16 MB, an `--out` that is a
directory, not `.json`, outside both roots, hidden in the repository or through a link), with
one line on stderr and nothing on stdout; 2 bad usage. The commit pin
also covers the gap between building and posting: a push after the build leaves the review on the
reviewed commit, shown as outdated, rather than on the new head.

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
  - Terraform (pack `terraform-patterns`; specificity 0, so any language stack beside it is the
    primary): format `terraform fmt -recursive` (applies, like every stack's format), typecheck
    `terraform init -backend=false && terraform validate`, and `terraform test` only when
    `tests/*.tftest.hcl` or a root `*.tftest.hcl` exists; lint `tflint --recursive` only when
    `.tflint.hcl` sits in the profile's directory (else none). The typecheck is a shell command (the
    commit gate refuses any command with shell syntax, and never runs tflint, so Terraform stays
    ungated at commit), and it is not read-only: `terraform init` downloads the providers and modules into `.terraform/` and may
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

**Status:** detection ships for the common stacks, and **every registered stack ships a
`*-patterns` pack** — python, typescript, javascript, go, rust, jvm, dotnet, ruby, php, and
terraform. `terraform` shipped detection-only first and gained `terraform-patterns` after a field
report (an Azure Policy change ran with no IaC conventions): the agent runs only offline checks
(fmt, `init -backend=false`, validate, mock-provider `terraform test`) and names the real-backend
`terraform plan` / `show -json` / apply as the human's step, tests run on mock providers with no cloud credentials, inputs are refused by `validation` blocks,
secrets stay out of tfvars, outputs and git, and documents built in HCL (`jsonencode`, policies)
are reviewed in the rendered plan JSON (`terraform show -json plan.out`), not only in the HCL.
An **unrecognized** repo (`unknown`) falls back to
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
   registered stack, terraform included (ADR 0015).
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
