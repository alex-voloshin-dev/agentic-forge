# Authoring a Python script

Scripts give skills deterministic, testable capability. No shell scripts — Python only.

## Where it lives

- **Shared / cross-cutting** logic -> `plugin/lib/agentic_forge/<module>.py`, imported by
  skills, hooks, and other scripts.
- **Skill-specific** executable -> `plugin/skills/<skill>/scripts/<name>.py`, invoked from
  the skill via `python ${CLAUDE_SKILL_DIR}/scripts/<name>.py ...`.

A skill-specific script may import from `agentic_forge` by adding `plugin/lib` to
`sys.path` (as `dev/validate.py` does) or via the installed package.

## Rules

- Self-contained or with clearly documented dependencies (keep deps light: stdlib first).
- A real CLI: argparse or `sys.argv`, helpful errors, and a `main(argv) -> int` returning
  an exit code (0 ok, non-zero failure). Skills depend on the exit-code contract.
- Pure functions where possible; side effects isolated and explicit.
- Type-annotated; passes `ruff` and `mypy --strict`.

## Tests (mandatory)

Every script ships pytest coverage in `tests/`:

- Unit-test the pure logic directly.
- For anything that calls an LLM or network, inject a seam and test with a mock/stub so
  the test is deterministic.
- Target >= 80% line coverage for the script's module.

## Checklist

- Correct location (lib vs skill `scripts/`); imports resolve at runtime.
- Exit-code contract honored; errors are actionable.
- pytest green; `ruff` + `mypy` clean; coverage >= 80%.
- A script-type `evals/evals.json` records its purpose and the coverage threshold.
