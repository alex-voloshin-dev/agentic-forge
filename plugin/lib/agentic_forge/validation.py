"""Tier-0 deterministic validation for the agentic-forge plugin.

Tier 0 is the always-blocking, LLM-free gate: standard compliance, frontmatter
sanity, body length, reference resolution, and the presence of a valid evals.json
contract. It is intentionally cheap so it can run on every save and every PR.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import evals as evals_mod
from . import models, naming, skill_contract
from .frontmatter import FrontmatterError, parse

__all__ = [
    "LISTING_BUDGET_CHARS",
    "listing_budget",
    "validate_listing_budget",
    "DESCRIPTION_MAX_LEN",
    "COMPATIBILITY_MAX_LEN",
    "BODY_MAX_LINES",
    "STANDARD_FIELDS",
    "CLAUDE_CODE_FIELDS",
    "KNOWN_FIELDS",
    "Issue",
    "Report",
    "validate_skill",
    "validate_agent",
    "validate_manifest",
    "validate_python_compat",
    "validate_plugin",
    "validate_docs",
    "MAINTAINER_SKILLS_DIR",
    "REPO_MARKER",
    "maintainer_skills_dir",
    "maintainer_root",
    "maintainer_skill_dirs",
    "validate_maintainer_skills",
]

DESCRIPTION_MAX_LEN = 1024
COMPATIBILITY_MAX_LEN = 500
BODY_MAX_LINES = 500

# Agent Skills standard frontmatter fields.
STANDARD_FIELDS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}

# Documented Claude Code extensions to the standard.
CLAUDE_CODE_FIELDS = {
    "when_to_use",
    "argument-hint",
    "arguments",
    "disable-model-invocation",
    "user-invocable",
    "disallowed-tools",
    "model",
    "effort",
    "context",
    "agent",
    "hooks",
    "paths",
    "shell",
}

KNOWN_FIELDS = STANDARD_FIELDS | CLAUDE_CODE_FIELDS

# Code spans (fenced ```blocks``` + inline `code`) — blanked before ref-scanning so a documented
# link *example* in a fence/backticks isn't mistaken for a real reference and failed by Tier-0.
_CODE_SPAN = re.compile(r"```[\s\S]*?```|`[^`\n]+`")
# Local references we expect to resolve on disk.
_LOCAL_REF = re.compile(r"(?:\]\(|\$\{CLAUDE_SKILL_DIR\}/)((?:references|assets|scripts)/[^)\s]+)")
# Cross-tree relative markdown links (`](../...)` / `](./...)`) — patterns, agents, docs, sibling
# skills. These resolve against the file's own directory and must exist (gates inter-dir link rot).
_RELATIVE_REF = re.compile(r"\]\((\.\.?/[^)\s#?]+)")


def _check_refs(text: str, base_dir: Path, loc: str, report: Report) -> None:
    """Error on any local (`references/`/`assets/`/`scripts/`) or relative (`../`,`./`) markdown
    reference in ``text`` that does not resolve under ``base_dir``. Code spans are blanked first so
    a documented link *example* in a fence/backticks isn't treated as a real reference."""
    text = _CODE_SPAN.sub("", text)
    for match in _LOCAL_REF.finditer(text):
        ref = match.group(1).split("#", 1)[0].split("?", 1)[0]  # drop #anchor / ?query
        if ref and not (base_dir / ref).exists():
            report.error(loc, f"referenced file does not exist: {ref}")
    for match in _RELATIVE_REF.finditer(text):
        ref = match.group(1)
        if not (base_dir / ref).exists():
            report.error(loc, f"referenced file does not exist: {ref}")


@dataclass
class Issue:
    severity: str  # "error" | "warning"
    location: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.location}: {self.message}"


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)

    def error(self, location: str, message: str) -> None:
        self.issues.append(Issue("error", location, message))

    def warning(self, location: str, message: str) -> None:
        self.issues.append(Issue("warning", location, message))

    def extend(self, other: Report) -> None:
        self.issues.extend(other.issues)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self) -> str:
        if not self.issues:
            return "Tier-0: OK (no issues)"
        lines = [str(i) for i in self.issues]
        lines.append(f"\n{len(self.errors)} error(s), {len(self.warnings)} warning(s)")
        return "\n".join(lines)


# --- the always-on listing budget (ADR 0095) ---------------------------------------------
#
# Every model-invocable skill's name + description sits in EVERY session's context. CLAUDE.md has
# carried a budget for it since ADR 0056 ("~1% of the model window ... adding an on-listing skill
# requires a budget review") and nothing measured it: the figure was recounted by hand, twice, in
# two years. This is that rule as a gate, and it is a RATCHET, not a ceiling — the listing is
# already at/over the ~1% guidance, so a number that failed "too big" would fail today and teach
# nothing. It fails GROWTH instead: a new on-listing skill (~600 chars) or a description that puts
# on weight trips it, an equal-length rewording does not. Raising the constant is the budget
# review, visible in the diff. ADR 0105 moved it DOWN to the measured shipped listing (10,257 ->
# 6,910 chars, 17 -> 16 skills: shorter descriptions, skill-factory no longer shipped), so the
# saved space cannot quietly fill again. Only shipped skills count; maintainer skills do not.
LISTING_BUDGET_CHARS = 6_910
_LISTING_NAMESPACE = "agentic-forge:"
_CHARS_PER_TOKEN = 4  # the usual English estimate; tiktoken is not a dependency of Tier-0


def listing_budget(plugin_dir: Path) -> tuple[int, list[tuple[str, int]]]:
    """Rendered size of the always-on skill listing: total chars, and per-skill, biggest first.

    Measures what a live session is shown — ``- agentic-forge:<name>: <description>`` per
    model-invocable skill — so the number is the listing's real context cost, not a proxy."""
    rows: list[tuple[str, int]] = []
    skills_dir = plugin_dir / "skills"
    if not skills_dir.is_dir():
        return 0, rows
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        md = skill_dir / "SKILL.md"
        if not md.is_file():
            continue
        try:
            fm, _ = parse(md.read_text(encoding="utf-8"))
        except (FrontmatterError, OSError):
            continue
        if str(fm.get("disable-model-invocation", "")).strip().lower() == "true":
            continue  # off-listing: manual /name only, not in the model's listing
        name = str(fm.get("name") or skill_dir.name)
        description = str(fm.get("description") or "").strip()
        rows.append((name, len(f"- {_LISTING_NAMESPACE}{name}: {description}")))
    rows.sort(key=lambda row: (-row[1], row[0]))
    return sum(n for _, n in rows), rows


def budget_line(plugin_dir: Path) -> str:
    """One line for every validate run — the budget is only a guard if it is visible when it
    passes (ADR 0082's lesson: a gate nobody reads reports nothing)."""
    total, rows = listing_budget(plugin_dir)
    return (
        f"listing budget: {total}/{LISTING_BUDGET_CHARS} chars "
        f"(~{total // _CHARS_PER_TOKEN} tokens, {len(rows)} on-listing skills)"
    )


def validate_listing_budget(plugin_dir: Path) -> Report:
    """Fail when the always-on listing grew past the recorded budget."""
    report = Report()
    total, rows = listing_budget(plugin_dir)
    if total > LISTING_BUDGET_CHARS:
        worst = ", ".join(f"{name} ({n})" for name, n in rows[:3])
        report.error(
            "listing-budget",
            f"the always-on skill listing is {total} chars (~{total // _CHARS_PER_TOKEN} tokens) "
            f"over a budget of {LISTING_BUDGET_CHARS}: it sits in EVERY session's context. "
            f"Tighten the longest descriptions ({worst}), move a router off-listing "
            "(disable-model-invocation: true), or raise validation.LISTING_BUDGET_CHARS "
            "deliberately — that constant IS the budget review (ADR 0095).",
        )
    return report


def validate_skill(skill_dir: Path, *, plugin_dir: Path | None = None) -> Report:
    """Run Tier-0 checks on a single skill directory.

    ``plugin_dir`` is the base its eval cases' ``files`` resolve against — by default the plugin
    the skill sits in (``<plugin>/skills/<name>``). A maintainer skill (ADR 0105) lives outside the
    plugin but its eval stand and the real ``schemas/evals.schema.json`` are in it, so its caller
    passes the plugin dir explicitly."""
    report = Report()
    rel = skill_dir.name
    skill_md = skill_dir / "SKILL.md"

    if not skill_md.is_file():
        report.error(rel, "missing SKILL.md")
        return report

    text = skill_md.read_text(encoding="utf-8")
    try:
        fm, body = parse(text)
    except FrontmatterError as exc:
        report.error(f"{rel}/SKILL.md", str(exc))
        return report

    # name (optional in CC; defaults to dir name). The directory name always becomes
    # the command name, so it must obey the standard's naming rules.
    for err in naming.validate_name(skill_dir.name):
        report.error(f"{rel}/SKILL.md", f"directory name: {err}")
    if "name" in fm:
        for err in naming.validate_name(str(fm["name"]), dir_name=skill_dir.name):
            report.error(f"{rel}/SKILL.md", f"name: {err}")

    # description (required by the standard).
    desc = fm.get("description")
    if not desc or not str(desc).strip():
        report.error(f"{rel}/SKILL.md", "description is required and must be non-empty")
    elif len(str(desc)) > DESCRIPTION_MAX_LEN:
        report.error(
            f"{rel}/SKILL.md",
            f"description exceeds {DESCRIPTION_MAX_LEN} characters (got {len(str(desc))})",
        )

    # compatibility (optional).
    compat = fm.get("compatibility")
    if compat is not None and len(str(compat)) > COMPATIBILITY_MAX_LEN:
        report.error(f"{rel}/SKILL.md", f"compatibility exceeds {COMPATIBILITY_MAX_LEN} characters")

    # metadata (optional): map of string -> string.
    meta = fm.get("metadata")
    if meta is not None:
        if not isinstance(meta, dict):
            report.error(f"{rel}/SKILL.md", "metadata must be a mapping")
        else:
            for key, value in meta.items():
                if not isinstance(value, str):
                    report.warning(
                        f"{rel}/SKILL.md", f"metadata.{key} should be a string value"
                    )

    # unknown fields (typo guard).
    for key in fm:
        if key not in KNOWN_FIELDS:
            report.warning(f"{rel}/SKILL.md", f"unknown frontmatter field '{key}'")

    # body length.
    line_count = body.count("\n") + 1 if body else 0
    if line_count > BODY_MAX_LINES:
        report.error(
            f"{rel}/SKILL.md",
            f"body is {line_count} lines; keep under {BODY_MAX_LINES} (move detail to references/)",
        )

    # local + cross-tree relative references must resolve.
    _check_refs(text, skill_dir, f"{rel}/SKILL.md", report)

    # evals.json contract is mandatory; its fixture files must exist (no silent rot).
    _check_evals(
        skill_dir / "evals" / "evals.json",
        f"{rel}/evals/evals.json",
        report,
        "skill",
        plugin_dir if plugin_dir is not None else skill_dir.parent.parent,
    )

    return report


def _check_evals(
    evals_path: Path, loc: str, report: Report, expected_type: str, plugin_dir: Path
) -> None:
    """Require a present, schema-valid evals contract whose component.type matches and whose
    eval-case fixture files all exist (so referenced fixtures can't silently rot)."""
    if not evals_path.is_file():
        report.error(loc, "missing required eval contract (readiness contract)")
        return
    try:
        data = evals_mod.load_evals(evals_path)
    except evals_mod.EvalsError as exc:
        report.error(loc, str(exc))
        return
    errors = evals_mod.validate_evals(data)
    for err in errors:
        report.error(loc, err)
    if errors:
        return
    actual = (data.get("component") or {}).get("type")
    if actual != expected_type:
        report.error(loc, f"component.type must be '{expected_type}', got '{actual}'")
    for case in data.get("evals") or []:
        for rel_file in case.get("files") or []:
            if not (plugin_dir / rel_file).is_file():
                report.error(loc, f"eval case {case.get('id')}: missing fixture file {rel_file}")


def validate_agent(agent_md: Path) -> Report:
    """Tier-0 checks for a subagent definition file and its eval contract."""
    report = Report()
    name = agent_md.stem
    rel = f"agents/{agent_md.name}"

    for err in naming.validate_name(name):
        report.error(rel, f"file name: {err}")

    text = agent_md.read_text(encoding="utf-8")
    try:
        fm, _ = parse(text)
    except FrontmatterError as exc:
        report.error(rel, str(exc))
        return report
    _check_refs(text, agent_md.parent, rel, report)

    if not fm.get("description"):
        report.error(rel, "agent description is required")
    fm_name = fm.get("name")
    if fm_name:
        for err in naming.validate_name(str(fm_name), dir_name=name):
            report.error(rel, f"name: {err}")

    # Runtime model routing (ADR 0046): the `model:` frontmatter must equal the committed,
    # gate-validated tier policy, so live `Task` delegation can't drift from what was validated.
    expected_model = models.frontmatter_model(name)
    actual_model = fm.get("model")
    if actual_model is None:
        report.error(rel, f"missing 'model' frontmatter (expected '{expected_model}')")
    elif str(actual_model) != expected_model:
        report.error(
            rel,
            f"model '{actual_model}' != the validated tier policy (expected '{expected_model}'); "
            "run `python dev/sync_models.py --apply`",
        )

    # Agents are gated like skills: a sibling eval contract is mandatory.
    evals_path = agent_md.parent / "evals" / f"{name}.evals.json"
    _check_evals(
        evals_path, f"agents/evals/{name}.evals.json", report, "agent", agent_md.parent.parent
    )

    return report


# Doc-sync (ADR 0017/0039 review pass): two living docs must track the tree, or they silently rot —
# the meta-core lib table and the ADR index. A markdown table row `| `name.py` | ... |`.
_LIB_TABLE_ROW = re.compile(r"^\|\s*`([a-z0-9_]+)\.py`\s*\|", re.MULTILINE)
# A link to an ADR file from the index: `](0007-....md)`.
_ADR_LINK = re.compile(r"\]\((\d{4}-[a-z0-9-]+\.md)\)")
_ADR_FILE = re.compile(r"^\d{4}-[a-z0-9-]+\.md$")


_ADR_CITATION = re.compile(r"ADR (\d{4})")
_CITATION_ROOTS = ("plugin", "docs", "CLAUDE.md", "README.md")


def _adr_citations(repo_root: Path) -> set[str]:
    """Every `ADR NNNN` referenced from outside `docs/architecture/decisions/`."""
    found: set[str] = set()
    for rel in _CITATION_ROOTS:
        target = repo_root / rel
        paths = [target] if target.is_file() else target.rglob("*")
        for path in paths:
            if not path.is_file() or path.suffix not in {".md", ".py", ".json"}:
                continue
            if "decisions" in path.parts or "__pycache__" in path.parts:
                continue
            try:
                found.update(_ADR_CITATION.findall(path.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError):
                continue
    return found


def validate_docs(repo_root: Path) -> Report:
    """Doc-sync checks that keep the two living indexes from drifting out of the tree:

    1. the `docs/architecture/meta-core.md` shared-library table lists exactly the modules in
       `plugin/lib/agentic_forge/` (no missing row, no stale row);
    2. every ADR file under `docs/architecture/decisions/` is linked from that dir's `README.md`
       index, and every index link resolves;
    3. an ADR that introduces a RULE is cited from at least one artifact outside `decisions/`
       (warning). In this repo the rule lives in the skill/pattern/agent and the *evidence* lives
       in the ADR — an uncited ADR is a rule whose field evidence is unreachable, so the next
       person it inconveniences deletes it. Two ADRs written on 2026-07-26 were orphaned this way.

    Cheap, deterministic, LLM-free — part of the Tier-0 gate when run from the repo root.
    """
    report = Report()

    # 1) lib table <-> lib modules.
    meta_core = repo_root / "docs" / "architecture" / "meta-core.md"
    lib_dir = repo_root / "plugin" / "lib" / "agentic_forge"
    if meta_core.is_file() and lib_dir.is_dir():
        loc = "docs/architecture/meta-core.md"
        documented = set(_LIB_TABLE_ROW.findall(meta_core.read_text(encoding="utf-8")))
        actual = {p.stem for p in lib_dir.glob("*.py") if p.stem != "__init__"}
        for missing in sorted(actual - documented):
            report.error(loc, f"lib module '{missing}.py' is not in the meta-core library table")
        for stale in sorted(documented - actual):
            report.error(loc, f"meta-core library table lists '{stale}.py', which no longer exists")

    # 2) every ADR is indexed, and every index link resolves.
    decisions = repo_root / "docs" / "architecture" / "decisions"
    index = decisions / "README.md"
    if decisions.is_dir() and index.is_file():
        loc = "docs/architecture/decisions/README.md"
        linked = set(_ADR_LINK.findall(index.read_text(encoding="utf-8")))
        on_disk = {p.name for p in decisions.glob("*.md") if _ADR_FILE.match(p.name)}
        for missing in sorted(on_disk - linked):
            report.error(loc, f"ADR '{missing}' is not linked from the decisions index")
        for dangling in sorted(linked - on_disk):
            report.error(loc, f"decisions index links '{dangling}', which does not exist")

        # 3) an ADR nothing cites (a WARNING — a purely procedural ADR legitimately has no
        # artifact to cite it, so this must not block the gate).
        cited = _adr_citations(repo_root)
        for name in sorted(on_disk):
            number = name[:4]
            if number not in cited:
                report.warning(
                    f"docs/architecture/decisions/{name}",
                    f"no artifact outside decisions/ cites 'ADR {number}' — a rule whose "
                    f"rationale cannot be found from the rule",
                )

    return report


# The shipped Python (lib + hooks + skill scripts) runs on whatever `python3` the USER has —
# macOS CommandLineTools still pins 3.9, and a real environment snapshot showed hooks running on
# 3.9.6. `from __future__ import annotations` keeps PEP 604/585 annotations lazy so a module
# import can't crash there (models.py imported fine on 3.11 but raised TypeError on 3.9).
_FUTURE_IMPORT = "from __future__ import annotations"


def validate_python_compat(plugin_dir: Path) -> Report:
    """Every non-empty RUNTIME ``.py`` (lib, hooks, shipped skill scripts) must carry the
    annotations future-import, so the module tree stays importable on the oldest user ``python3``
    (3.9) the hooks are contracted to survive on (ADR 0050). Eval fixtures are exempt — they are
    test *subjects*, not code that runs on a user's interpreter."""
    report = Report()
    runtime_files: list[Path] = []
    for root in (plugin_dir / "lib", plugin_dir / "hooks", plugin_dir / "bin"):
        runtime_files.extend(root.rglob("*.py"))
    runtime_files.extend((plugin_dir / "skills").glob("*/scripts/*.py"))
    for path in sorted(runtime_files):
        if "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            report.error(str(path.relative_to(plugin_dir)), f"unreadable: {exc}")
            continue
        if text.strip() and _FUTURE_IMPORT not in text:
            report.error(
                str(path.relative_to(plugin_dir)),
                f"missing '{_FUTURE_IMPORT}' (shipped code must import on the user's bare "
                "python3, which may be 3.9 — ADR 0050/0054 review)",
            )
    return report


# Inline Python takes the working directory's modules before the standard library's, so a checkout
# could run code as the user, and it needs the library importable, which a plugin-only install does
# not give it (ADR 0104). `-c`, `-`, a heredoc and stdin all do; so does `-m` for the library.
_PYTHON = r"\bpython[0-9.]*"
_PYTHON_FLAGS = r"(?:\s+-[WX]\s*\S+|\s+-[A-Za-z]+)*?"
_INLINE_PYTHON = re.compile(
    rf"{_PYTHON}{_PYTHON_FLAGS}\s+(?:-[A-Za-z]*c\b|-(?=\s|$)|/dev/stdin\b|-m\s+agentic_forge\b)"
    rf"|{_PYTHON}{_PYTHON_FLAGS}\s*<"
    rf"|\|\s*{_PYTHON}{_PYTHON_FLAGS}\s*$"
    r"|\bfrom\s+agentic_forge(?:\.\w+)*\s+import\b|\bimport\s+agentic_forge\b"
    r"|\b(?:__import__|import_module)\(\s*[\"']agentic_forge",
    re.MULTILINE,
)
# A shipped script without -E: PYTHONPATH reaches the interpreter before the script's first line,
# and a project's settings can set it. Only -E, which keeps user site-packages (ADR 0104).
_SCRIPT_WITHOUT_E = re.compile(
    rf"{_PYTHON}(?:\s+-(?!E\b)\S+)*\s+[\"']?[^\s\"']*/(?:bin|scripts)/[^\s\"']+\.py"
)


def validate_no_inline_python(plugin_dir: Path) -> Report:
    """No skill, reference, pattern or role tells a model to run inline Python: what a skill needs
    is a command in ``bin/af.py`` or a script of its own (ADR 0104). Eval fixtures are exempt, being
    test subjects, and so are a skill's own scripts, which run in script mode."""
    report = Report()
    for root in ("skills", "patterns", "agents"):
        for path in sorted((plugin_dir / root).rglob("*.md")):
            _inline_python_problems(path, path.relative_to(plugin_dir).as_posix(), report)
    return report


def _inline_python_problems(path: Path, loc: str, report: Report) -> None:
    """The ADR 0104 checks on one markdown file, reported at ``<loc>:<line>``."""
    text = path.read_text(encoding="utf-8")
    lines = {text.count("\n", 0, m.start()) + 1 for m in _INLINE_PYTHON.finditer(text)}
    for line in sorted(lines):
        report.error(
            f"{loc}:{line}",
            "inline Python: a checkout could supply the module it imports; add a "
            "command to bin/af.py instead (ADR 0104)",
        )
    lines = {text.count("\n", 0, m.start()) + 1 for m in _SCRIPT_WITHOUT_E.finditer(text)}
    for line in sorted(lines):
        report.error(
            f"{loc}:{line}",
            "a shipped script run without python3 -E: PYTHONPATH could reach the "
            "interpreter before the script does (ADR 0104)",
        )


# --- maintainer skills (ADR 0105) ---------------------------------------------------------
#
# A skill that builds THIS repository (`skill-factory`) is useless in a user's project, and every
# shipped description takes a share of one listing budget common to all plugins. So it lives in
# the repo's `.claude/skills/`, which Claude Code loads for a session in this repo (bare name, no
# namespace), and does not ship. Not shipping must not mean not gated: Tier-0 runs the same
# `validate_skill` over it and the same body checks. What it does NOT get: the listing budget
# (it is in no user's listing) and the 3.9 import rule (it is not run by a user's `python3`).
MAINTAINER_SKILLS_DIR = Path(".claude") / "skills"
# What makes a directory THIS repository (the doc-sync checks key on it too). Without it, a plugin
# validated from `~/some-plugin` would treat the user's personal `~/.claude/skills` as ours.
REPO_MARKER = Path("docs") / "architecture" / "meta-core.md"


def maintainer_skills_dir(repo_root: Path) -> Path:
    """Where a repository keeps its maintainer (project) skills: ``<repo>/.claude/skills``."""
    return repo_root / MAINTAINER_SKILLS_DIR


def maintainer_root(repo_root: Path) -> Path | None:
    """The maintainer skills dir — or None unless ``repo_root`` is the agentic-forge repository
    (it has :data:`REPO_MARKER`) and the dir exists. The one place the eval CLIs and the validator
    decide whether there are maintainer skills to read."""
    if not (repo_root / REPO_MARKER).is_file():
        return None
    root = maintainer_skills_dir(repo_root)
    return root if root.is_dir() else None


def maintainer_skill_dirs(repo_root: Path) -> list[Path]:
    """Every maintainer skill directory, sorted; empty when there is no :func:`maintainer_root`."""
    root = maintainer_root(repo_root)
    if root is None:
        return []
    return sorted(p for p in root.iterdir() if p.is_dir())


def validate_maintainer_skills(repo_root: Path, plugin_dir: Path) -> Report:
    """Tier-0 for ``<repo>/.claude/skills/*``: the full ``validate_skill`` (eval ``files`` resolve
    against ``plugin_dir``, where the eval stands live), the inline-Python checks on every markdown
    file, and no name shared with a shipped skill — the Tier-2 resolver looks in the plugin first,
    so a namesake would be silently shadowed. Locations are repo-relative."""
    report = Report()
    shipped = plugin_dir / "skills"
    for skill_dir in maintainer_skill_dirs(repo_root):
        sub = validate_skill(skill_dir, plugin_dir=plugin_dir)
        rel = skill_dir.relative_to(repo_root).as_posix()
        for issue in sub.issues:  # `<name>/SKILL.md` -> `.claude/skills/<name>/SKILL.md`
            location = f"{MAINTAINER_SKILLS_DIR.as_posix()}/{issue.location}"
            report.issues.append(Issue(issue.severity, location, issue.message))
        if (shipped / skill_dir.name).is_dir():
            report.error(
                f"{rel}/SKILL.md",
                f"maintainer skill '{skill_dir.name}' shares its name with a shipped skill "
                f"(plugin/skills/{skill_dir.name}); the plugin one would shadow it in Tier-2",
            )
        for path in sorted(skill_dir.rglob("*.md")):
            _inline_python_problems(path, path.relative_to(repo_root).as_posix(), report)
    return report


def validate_manifest(plugin_dir: Path) -> Report:
    report = Report()
    manifest = plugin_dir / ".claude-plugin" / "plugin.json"
    if not manifest.is_file():
        report.error("plugin", "missing .claude-plugin/plugin.json")
        return report
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report.error("plugin/.claude-plugin/plugin.json", f"invalid JSON: {exc}")
        return report
    for key in ("name", "version"):
        if key not in data:
            report.error("plugin/.claude-plugin/plugin.json", f"missing required key '{key}'")
    return report


MARKETPLACE = Path(".claude-plugin") / "marketplace.json"


def validate_marketplace(repo_root: Path, plugin_dir: Path) -> Report:
    """The marketplace entry that lists this plugin carries the plugin's own version.

    A release bumps both files. 2026.11.8 bumped only plugin.json, and the marketplace went on
    advertising 2026.11.7 with nothing to catch it (ADR 0108). Skipped when the repo has no
    marketplace file or the manifest is unreadable (validate_manifest reports that).
    """
    report = Report()
    market = repo_root / MARKETPLACE
    if not market.is_file():
        return report
    loc = MARKETPLACE.as_posix()
    try:
        data = json.loads(market.read_text(encoding="utf-8"))
        plugin = json.loads((plugin_dir / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    except json.JSONDecodeError as exc:
        report.error(loc, f"invalid JSON: {exc}")
        return report
    except OSError:
        return report
    name, version = plugin.get("name"), plugin.get("version")
    entries = data.get("plugins") if isinstance(data, dict) else None
    listed = [e for e in entries or [] if isinstance(e, dict) and e.get("name") == name]
    if not listed:
        report.error(loc, f"no plugins[] entry named '{name}'")
    for entry in listed:
        if entry.get("version") != version:
            report.error(
                loc,
                f"'{name}' is listed at version {entry.get('version')!r}, but plugin.json is "
                f"{version!r}; a release bumps both",
            )
    return report


def validate_plugin(plugin_dir: Path) -> Report:
    """Validate the whole plugin: manifest, python compat, skills, agents."""
    report = Report()
    report.extend(validate_manifest(plugin_dir))
    report.extend(validate_python_compat(plugin_dir))
    report.extend(validate_no_inline_python(plugin_dir))
    report.extend(validate_listing_budget(plugin_dir))

    skills_dir = plugin_dir / "skills"
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir()):
            if child.is_dir():
                report.extend(validate_skill(child))

    agents_dir = plugin_dir / "agents"
    if agents_dir.is_dir():
        for child in sorted(agents_dir.glob("*.md")):
            report.extend(validate_agent(child))

    # Skill-body contract guards (ADR 0032/0033) over the skills present in this dir: documented
    # handoff fields + the spine recall step. Map/spine completeness vs the real plugin is asserted
    # separately by pytest, so the aggregate validator stays correct on a partial plugin too.
    def _present(name: str) -> bool:
        return (plugin_dir / "skills" / name / "SKILL.md").is_file()

    handoff_map = {s: t for s, t in skill_contract.SKILL_HANDOFF.items() if _present(s)}
    for problem in skill_contract.handoff_contract_problems(plugin_dir, handoff_map):
        report.error("skill-contract", problem)
    spine_present = tuple(s for s in skill_contract.SPINE_SKILLS if _present(s))
    for problem in skill_contract.recall_problems(plugin_dir, spine_present):
        report.error("knowledge-recall", problem)

    return report
