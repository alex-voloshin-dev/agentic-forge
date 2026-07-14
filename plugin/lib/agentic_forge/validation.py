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


def validate_skill(skill_dir: Path) -> Report:
    """Run Tier-0 checks on a single skill directory."""
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
        skill_dir.parent.parent,
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


def validate_docs(repo_root: Path) -> Report:
    """Doc-sync checks that keep the two living indexes from drifting out of the tree:

    1. the `docs/architecture/meta-core.md` shared-library table lists exactly the modules in
       `plugin/lib/agentic_forge/` (no missing row, no stale row);
    2. every ADR file under `docs/architecture/decisions/` is linked from that dir's `README.md`
       index, and every index link resolves.

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
    for root in (plugin_dir / "lib", plugin_dir / "hooks"):
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


def validate_plugin(plugin_dir: Path) -> Report:
    """Validate the whole plugin: manifest, python compat, skills, agents."""
    report = Report()
    report.extend(validate_manifest(plugin_dir))
    report.extend(validate_python_compat(plugin_dir))

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
