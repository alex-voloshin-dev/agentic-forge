# Authoring a skill

A skill is a directory `<name>/` with `SKILL.md` plus optional `references/`,
`assets/`, `scripts/`, and the required `evals/evals.json`. It must validate with
`skills-ref` and `dev/validate.py`.

## Frontmatter

Required by the standard:

- `name` — must equal the directory name; 1-64 chars; lowercase `a-z 0-9 -`; no leading/
  trailing or doubled hyphen.
- `description` — <=1024 chars; says **what it does and when to use it**, with trigger
  keywords a user would actually type. This is the single biggest lever on auto-loading.

Common Claude Code extensions (use only when needed):

- `disable-model-invocation: true` — manual-only (`/name`); for side-effecting actions
  (deploy, commit, send). Removes the description from context.
- `user-invocable: false` — Claude-only background knowledge; not a meaningful command.
- `allowed-tools` — pre-approve tools while active (e.g. `Read, Write, Edit, Grep, Glob`).
- `context: fork` + `agent` — a Claude Code field binding the skill to one subagent type;
  **this plugin does not use it** — skills delegate at runtime via the `Task` tool instead.
- `paths` — glob(s) that gate auto-loading to matching files.
- `argument-hint`, `arguments`, `model`, `effort` — as documented.

## Body rules

- Keep under 500 lines; move detail to `references/` (one level deep) and reference each
  file so Claude knows when to load it.
- Write standing instructions, not narration — the body stays in context across turns,
  so every line is recurring cost.
- State *what to do* and *why* briefly; avoid rigid ALWAYS/NEVER walls.
- Dynamic context: `` !`command` `` runs before the skill loads and inlines output.
  `${CLAUDE_SKILL_DIR}` resolves to this skill's directory for script paths.

## Router vs leaf

- **Router skill** (domain entry): sharp description, small body, delegates depth to
  `references/` and possibly forked subagents. Few of these; they carry auto-loading.
- **Leaf/knowledge skill**: often `user-invocable: false`; pulled in by Claude as
  background context. Keep descriptions specific so they do not crowd the listing budget.

## Checklist

- Directory name == `name`; description has real trigger keywords.
- Body < 500 lines; references resolve; no absolute paths.
- `evals/evals.json` written first, with `triggers` and `thresholds`.
- `dev/validate.py` clean before running quality evals.
