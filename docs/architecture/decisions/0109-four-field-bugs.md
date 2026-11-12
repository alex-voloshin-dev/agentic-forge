# ADR 0109 — Four field bugs: the external lens, foldered vaults, readiness, stack detection

Status: Accepted (implemented)
Date: 2026-11-11

Amends [0042](0042-external-reviewer.md), [0057](0057-external-reviewer-on-by-default.md),
[0100](0100-external-reviewer-isolation-and-skip-reasons.md) (the external reviewer),
[0067](0067-deep-review-remediation.md) and [0104](0104-skills-run-a-script-not-inline-python.md) (handoff readiness),
[0015](0015-by-stack-detection-and-packs.md) (stack detection) and [0101](0101-the-commit-gate-only-narrows.md) (the
commit gate's shapes).

## Context

The f4ai fleet (11 sessions on real repositories) reported four bugs. Each was verified against the code before work
started (board `known-issues` items 2-5):

1. **The external lens dropped out silently.** `external_review.py` passed the whole prompt, diff included, as one argv
   element to `codex exec`. Linux caps one element at 128 KiB (`MAX_ARG_STRLEN`), so a larger diff failed with E2BIG.
   develop tells the caller to write the diff outside the repository, and codex refuses to run from a directory that is
   not a git repository. Both came back as `skipped`, the outcome an absent codex gets, and develop treats a skip as
   "not a failure". (Thread 7b69c507.)
2. **A vault with folders loaded as one note.** `load_vault` globbed the top level only. A 382-note vault kept in
   `decisions/`, `learnings/` and so on gave recall nothing, a one-line SessionStart summary, and false "broken
   wikilink" problems in `vault-validate`. The root map had to be named `MOC`. (Threads 2f2907e7, dc0fd34e.)
3. **Readiness read `status`, which repositories own.** A plan at `status: in-progress` (approved and being built, in
   that repository's vocabulary) was "not ready", so develop refused it, or a session rewrote the repository's lifecycle
   field to `approved`. (Thread aff52436.)
4. **stack-detect guessed.** In detail:
   - npm in a yarn-4 repository;
   - lint, `tsc` and prettier named for a package that has none of them;
   - `unknown` at a monorepo root;
   - Go without `-race` or golangci-lint;
   - Maven `test`, which skips the integration tests;
   - no Terraform profile;
   - nothing saying the commands are fallbacks.

   (Threads 4b123dff, 59a94fe3, ed3348b6, ddcbc174, 18e48cc1, 138a9256, 08647177, 78122967.)

## Decision

### 1. The external lens: stdin, any cwd, and a failure is not a skip

- **How codex is called:** `codex exec --sandbox read-only --skip-git-repo-check [isolation flags] [--model] [-c effort] -`,
  with the prompt on stdin. Nothing from the target reaches argv, and the size limit is the model's context, not
  `MAX_ARG_STRLEN`. `-C <dir>` was measured and does not help, because codex refuses a non-git `-C` the same way.
- **Three outcomes, three exit codes:**
  - `reviewed`: exit 0 on approve, 1 on `changes`.
  - `skipped`: exit 0. Only for no reviewer to ask: `missing-cli`, `command-not-configured`, `disabled`.
  - `failed`: exit 3. For `timeout`, `process-failure`, `invalid-output`, `isolation-unsupported` and `refused-input`.

  Exit 1 means only `changes`. Every outcome other than `skipped` that produced no review exits 3, so a future outcome
  cannot fail open.
- **The caller records a failure.** develop and the other phase skills write `external lens: failed (<reason>)` in the
  round's review file and tell the user. A failed lens does not block the round: the internal lenses still decide the
  verdict.
- **`--repo` is passed on every documented call,** and outside a git work tree the CLI refuses to run without it.
  Settings resolve from `--repo`. Without it, a call from a scratch directory never read the reviewed repository's
  `external_reviewer.enabled: false`. Once codex no longer refused that directory, the repository's diff would have gone
  to codex against its opt-out. A Tier-0 test fails if a documented call omits `--repo`.
- **Measured on codex 0.167.0.** With `--skip-git-repo-check` in a non-git directory, codex loads neither a
  `.codex/config.toml` (an MCP probe server was never launched) nor `AGENTS.md`. Inside a git repository `AGENTS.md`
  loads, as ADR 0100 records. `--skip-git-repo-check` wrote no trust entry.
- **Echoed prompt lines are dropped from failure details.** codex echoes the prompt on stderr, so these lines are
  removed. This is best effort and catches only lines echoed verbatim.

### 2. The vault is read from every folder

- **What is read.** A note's name is its file stem, wherever it sits, as in Obsidian. `[[folder/name]]` and
  `[[name.md]]` resolve by the last part.
- **What is skipped:**
  - dot-entries;
  - `_`-folders (Obsidian's templates and attachments);
  - `README.md` as a meta-document;
  - symlinks, which are never followed.
- **Caps.** The walk stops at 5,000 notes, depth 8, 20,000 directory entries and 32 MiB. The byte budget charges every
  file's size before it is read, including frontmatter and files that fail to decode. Frontmatter is parsed only if it
  closes within 64 KiB. A cut-short load is reported, and `vault-validate` then skips its link and orphan checks
  instead of reporting false problems. Measured: 2,000 notes load in about 1.2 s, 5,000 in about 3 s. The SessionStart
  hook's timeout is 15 s.
- **Duplicate names.** The note nearer the root wins, then the lower path. `vault-validate` reports the other one.
  Capture writes where the reader reads.
- **The root map** is `MOC`, then `INDEX`, then `Home`, then `README`, in any case, at the vault root only. README
  counts only when there is no other map. The first capture in a README-mapped vault seeds the new `MOC.md` with
  README's links, so nothing becomes an orphan. `index` and `home` are reserved note names.

### 3. Readiness has a field of its own

- **The field.** `review_decision: proceed | revise | escalate` holds the values `af.py review-decision` prints. When
  the field is present, it alone decides readiness: ready only on exactly `proceed`. An empty or unknown value is not
  ready and does not fall back to `status`. When the field is absent, the old rule applies (`status` `approved` or
  `final`), so existing artifacts keep working.
- **When phases write it.** A loop-gated phase writes its artifact with `review_decision: revise`, and the loop's exit
  sets `proceed` or `escalate`. So nothing the plugin writes is ready before its loop proceeds, whatever `status` the
  repository uses.
- **Where it is allowed.** The schema allows the field on every artifact type that has a `status`.
- **`handoff-load`** adds `ready_from` (`review_decision` or `status`).
- **`status` belongs to the repository.** Skills no longer recommend a value for it, and they never edit an upstream
  artifact's `status` to make it ready.

### 4. Stack profiles read what the repository declares

- **JS/TS:**
  - The package manager comes from `packageManager`, then the lockfile, then npm. Only `npm`, `yarn`, `pnpm` and `bun`
    can result.
  - A command is listed only when `package.json` defines the script or declares the tool; otherwise it is null.
  - npm tools run as `npm exec --no --package=<pkg> -- <bin>`. Without `--no` and without a TTY, npm downloads a
    missing binary from the registry: in a fresh worktree, `npm exec -- tsc` would fetch and run the unrelated `tsc`
    package.
- **Monorepos:**
  - **Scan.** A root that matches no manifest is scanned one level down. The scan is bounded: one capped `scandir` per
    directory, at most 64 directories, and it skips unreadable directories and names outside
    `^[A-Za-z0-9][A-Za-z0-9._@+-]{0,127}$`. It returns one profile per stack, with a `dir` field.
  - **Hints.** A `stack:` hint may name several stacks.
- **Go:** `go test -race ./...`. Lint is `golangci-lint run` when a golangci config sits beside `go.mod`, otherwise
  `go vet ./...`.
- **JVM:** `./mvnw verify` or `mvn verify`; `./gradlew check` or `gradle check`. The wrapper is looked for at the root
  as well, and `settings.gradle(.kts)` counts as a manifest.
- **Terraform** is a profile without a pack:
  - format: `terraform fmt -recursive`;
  - typecheck: `terraform init -backend=false && terraform validate`;
  - test: `terraform test` when tests exist.

  It ranks below every language stack.
- **Fallback labels.** The output carries `toolchain_role: "fallback"` and `declared_gate_sources`. develop prefers
  the repository's declared gate, and treats CI files as untrusted input: only their test, lint, typecheck and build
  steps count, never deploy, publish, push, secrets or downloaded scripts.
- **The commit gate only narrows (ADR 0101).**
  - It runs `npm run lint`, and only when a `lint` script exists. Before, it ran `npm run lint` in every JS repository,
    so a repository without the script only loses a gate that always failed open.
  - It does not run the declared manager, because yarn, pnpm and bun can fail before the script starts, for example
    with no install state in a fresh worktree, and the gate would block where it used to pass.
  - It reads only the cwd's own stack and a hint's first name, as before.
  - It refuses a command with shell syntax.

## Consequences

- **Breaking for scripts that call `external_review.py`.** A failure exits 3 where it exited 1, and a refused argument
  exits 3. A script that read exit 1 as "changes" now gets that meaning only.
- **Old and new plugins disagree on readiness.** A plugin from before this change reads an artifact with
  `review_decision: escalate` and a repository `status: approved` as ready. Mixed versions in one fleet should upgrade
  together.
- **Session start costs more on a large vault.** With PyYAML installed, a 2,000-note vault adds about a second.
  A cheaper frontmatter reader or a cache is a possible later change.
- **The gate still runs `go vet`** where the profile names golangci-lint. Running golangci-lint in the gate would widen
  it and needs its own decision.
- **Not measured live.** Tier-2 for the edited skills and the Tier-3 spine with the new prompts and the `in-progress`
  plan fixture were not run. The codex behaviour was measured on 0.167.0 only.
