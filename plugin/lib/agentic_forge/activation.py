"""Tier-1b: does the model INVOKE a skill on its own, unprompted (ADR 0088)?

Tier-1 (``tier1_runner``) asks the router "which skill fits?" and the router answers correctly at
recall 1.000. Tier-3 runs skills the harness invokes directly. Neither measures the thing the field
bundles showed failing: a live session, asked to *do* a task, does the work with Bash/Read instead
of calling the skill whose whole job is that workflow (ADR 0081 — 183 ``Agent`` calls vs 3
``Skill``; reproduced 2/2 in headless sessions on this very repo). "Routes correctly when asked"
and "reaches for the skill unasked" are different properties, and only the second matches how a
skill is actually used.

This module measures the second. Each skill's ``should_trigger`` prompts are run through a REAL
Claude Code session with the plugin loaded; the transcript is scanned for a ``Skill`` tool call
naming that skill. The metric is the activation rate — the fraction of prompts on which the model
reached for the skill. Pure parsing (``skill_invoked`` / ``activation_rate`` / ``run_activation``);
the subprocess seam lives in the CLI, like the other tiers.

This is a MEASUREMENT first, not a gate: there is no defensible threshold until a baseline exists,
so ``run_activation`` reports rates and only flags a shortfall when a ``min_activation`` is given.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentic_forge.agent_eval import Runner
from agentic_forge.tier1_runner import SkillTrigger, load_triggers

__all__ = [
    "ActivationReport",
    "FIXTURE_REPO",
    "FIXTURE_DOCS",
    "prepare_workspace",
    "WHY_PROMPT",
    "WHY_BUCKETS",
    "skill_invoked",
    "session_id_of",
    "bucket_why",
    "activation_rate",
    "run_activation",
]

def skill_invoked(stream: str, target: str) -> bool:
    """True if the transcript ``stream`` contains a ``Skill`` tool call naming ``target``.

    Scans every JSON object in the stream (one per line for ``--output-format stream-json``, or a
    single ``--output-format json`` envelope) for an assistant ``tool_use`` block whose tool is
    ``Skill`` and whose skill argument is ``target`` — bare or namespaced (``agentic-forge:x``
    matches target ``x``). A skill the model merely *names in prose* does not count: it must be an
    actual tool call, because acting-vs-routing is the whole point (ADR 0088)."""
    bare = target.split(":")[-1]
    for obj in _objects(stream):
        for block in _tool_use_blocks(obj):
            if block.get("name") != "Skill":
                continue
            inp = block.get("input") or {}
            named = str(inp.get("skill") or inp.get("name") or inp.get("command") or "")
            if named.split(":")[-1] == bare:
                return True
    return False


# What a prompt needs to find when it looks around. The first Tier-1b runs used one EMPTY temp dir
# for all 84 prompts: "review my PR", "build from the plan", "audit this module" had no PR, no plan,
# no module — the session looked, found nothing (or a PRD another prompt's skill had written into
# the shared dir), and asked where the code was. The eval scored that as "did the work by hand".
# 36 of 36 stated reasons said so (ADR 0090). Now every prompt gets a fresh copy of the Tier-3
# fixture: a small Python repo with a git history, the SDLC artifacts a spine phase expects, a
# feature branch with a committed change, and an unstaged edit — so a diff, a PR-shaped branch, a
# plan and a module all exist to be reviewed, implemented against, or audited.
FIXTURE_REPO = "eval/fixtures/spine/target-repo"
FIXTURE_DOCS = {  # src (relative to the plugin) -> dest (relative to the workspace)
    "eval/fixtures/spine/research-brief.md": "docs/sdlc/task-priorities/research-brief.md",
    "eval/fixtures/spine/prd.md": "docs/sdlc/task-priorities/prd.md",
    "eval/fixtures/spine/tech-design.md": "docs/sdlc/task-priorities/tech-design.md",
    "eval/fixtures/spine/plan.md": "docs/sdlc/task-priorities/plan.md",
    # ADR 0091 stand polish: a page to audit and a UI to design, so `marketing` and
    # `ux-design` prompts have a target the way the code prompts do.
    "eval/fixtures/activation/blog-post.md": "docs/blog/why-task-priorities.md",
    "eval/fixtures/activation/task-list.html": "web/task-list.html",
}
_FEATURE_BRANCH = "feature/task-priorities"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
        env={"GIT_AUTHOR_NAME": "eval", "GIT_AUTHOR_EMAIL": "eval@example.invalid",
             "GIT_COMMITTER_NAME": "eval", "GIT_COMMITTER_EMAIL": "eval@example.invalid",
             "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
    )


def prepare_workspace(plugin_dir: Path, dest: Path) -> Path:
    """Materialize ``dest/repo`` as the workspace a Tier-1b prompt runs in (ADR 0090).

    A copy of the spine fixture repo with the SDLC docs seeded, ``git init`` + a baseline commit
    on ``main``, then a feature branch carrying one committed change AND one unstaged edit — so
    ``git diff``, ``git diff main..HEAD`` and "this branch" all have content, and "the plan" is a
    real file. Idempotent per call; each prompt should get its own ``dest``."""
    repo = dest / "repo"
    if repo.exists():
        shutil.rmtree(repo)
    shutil.copytree(
        plugin_dir / FIXTURE_REPO, repo, ignore=shutil.ignore_patterns("__pycache__")
    )
    for src, rel in FIXTURE_DOCS.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((plugin_dir / src).read_text(encoding="utf-8"), encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")
    _git(repo, "checkout", "-q", "-b", _FEATURE_BRANCH)
    module = repo / "taskstore.py"
    module.write_text(
        module.read_text(encoding="utf-8")
        + "\n\ndef priority_of(task: dict) -> int:\n"
        "    \"\"\"Task priority (1 = highest); missing means lowest.\"\"\"\n"
        "    return int(task.get(\"priority\", 5))\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feat: task priority accessor (step 1 of the plan)")
    readme = repo / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8") + "\n## Priorities\n\nTasks carry a priority.\n",
        encoding="utf-8",
    )  # unstaged: `git diff` is non-empty too
    return repo


def session_id_of(stream: str) -> str | None:
    """The session id a stream-json transcript was recorded under (from its `init` object), so a
    miss can be asked, in the same session, why it did the work by hand (ADR 0088, step 4)."""
    for obj in _objects(stream):
        sid = obj.get("session_id")
        if sid and obj.get("type") == "system":
            return str(sid)
    for obj in _objects(stream):
        if obj.get("session_id"):
            return str(obj["session_id"])
    return None


# The follow-up put to a session that did NOT invoke the skill. Deliberately neutral: it names the
# skill it had available and asks for the reason, without proposing one — a question that suggests
# "cost" would harvest "cost". Self-reports are claims, not measurements (a fork once fabricated an
# approval, ADR 0073); across 40+ misses the DISTRIBUTION is still the cheapest signal available on
# what the model thinks it is choosing between.
WHY_PROMPT = (
    "For the request above, the `{namespace}:{skill}` skill was available to you and you did the "
    "work directly instead of invoking it. In one or two sentences: why? State the actual reason "
    "behind that choice."
)

# Crude buckets over the stated reasons — keyword families, first match wins, reported alongside
# the raw text so nobody has to trust the buckets.
WHY_BUCKETS: dict[str, tuple[str, ...]] = {
    # First, because it turned out to be the whole story of the first run (ADR 0090): the session
    # had nothing to run the skill ON — an empty workdir, a placeholder in the prompt, no target.
    "nothing-to-work-on": ("empty", "nothing to", "no diff", "no code", "no plan", "no pr ",
                           "no target", "no design", "no docs", "no change", "not a git",
                           "only a prd", "placeholder", "dead end", "didn't find", "did not find",
                           "couldn't find", "nothing there", "nothing here", "no incident",
                           "пуст", "не было", "нет кода", "ничего"),
    "cost/overhead": ("overhead", "heavy", "heavyweight", "expensive", "slow", "longer", "too much",
                      "overkill", "faster", "quicker", "efficient", "lightweight", "cost"),
    # NOT "directly": the question itself says "did the work directly", and the answer echoes it.
    "task-is-simple": ("simple", "straightforward", "small", "trivial", "quick", "one-liner",
                       "just ", "single", "one-line", "minimal", "snap judgment"),
    "not-noticed": ("didn't notice", "did not notice", "unaware", "not aware", "didn't see",
                    "did not see", "forgot", "overlooked", "wasn't aware", "missed"),
    "not-applicable": ("not applicable", "doesn't apply", "does not apply", "did not apply",
                       "didn't apply", "not a match",
                       "didn't fit", "did not fit", "not needed", "unnecessary", "no need",
                       "not required", "different", "mismatch"),
    "no-artifacts-wanted": ("artifact", "handoff", "worktree", "document", "report", "file"),
}


def bucket_why(answer: str) -> str:
    low = answer.lower()
    for name, keys in WHY_BUCKETS.items():
        if any(k in low for k in keys):
            return name
    return "other"


def _objects(stream: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in stream.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _tool_use_blocks(obj: dict[str, Any]) -> list[dict[str, Any]]:
    """The ``tool_use`` content blocks of an assistant message, however the envelope nests them."""
    msg = obj.get("message", obj)
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]


@dataclass
class ActivationReport:
    """One skill's Tier-1b result: how often a live session reached for it unprompted."""

    skill: str
    activated: int
    prompts: int
    rate: float
    passed: bool
    gated: bool = False  # False when run as a pure measurement (no threshold) — ADR 0088
    reasons: list[str] = field(default_factory=list)
    misses: list[str] = field(default_factory=list)  # prompts where the skill was NOT invoked
    why: list[tuple[str, str]] = field(default_factory=list)  # (prompt, stated reason) per miss

    def summary_line(self) -> str:
        status = "----" if not self.gated else ("PASS" if self.passed else "FAIL")
        suffix = "  (" + "; ".join(self.reasons) + ")" if self.reasons else ""
        frac = f"({self.activated}/{self.prompts})"
        return f"[{self.skill}] {status}  activation={self.rate:.3f} {frac}{suffix}"


def activation_rate(
    trig: SkillTrigger,
    run_fn: Runner,
    workdir: Path,
    *,
    target: str,
    min_activation: float | None,
    ask_why: Callable[[str, str], str] | None = None,
    namespace: str = "agentic-forge",
    workspace_factory: Callable[[], Path] | None = None,
) -> ActivationReport:
    """Fraction of ``trig``'s should_trigger prompts on which a live session invoked the skill.

    ``ask_why(session_id, question)`` — when given — is called for every miss whose transcript has
    a session id, with :data:`WHY_PROMPT` filled in; the answer is kept beside the prompt."""
    activated = 0
    misses: list[str] = []
    why: list[tuple[str, str]] = []
    for prompt in trig.should_trigger:
        cwd = workspace_factory() if workspace_factory else workdir
        stream = run_fn("", prompt, cwd)
        if skill_invoked(stream, target):
            activated += 1
            continue
        misses.append(prompt)
        if ask_why is None:
            continue
        sid = session_id_of(stream)
        if sid:
            question = WHY_PROMPT.format(namespace=namespace, skill=trig.name)
            try:
                why.append((prompt, ask_why(sid, question).strip()))
            except Exception as exc:  # noqa: BLE001 — a lost follow-up must not lose the measurement
                why.append((prompt, f"<follow-up failed: {type(exc).__name__}>"))
    n = len(trig.should_trigger)
    rate = activated / n if n else 0.0
    reasons: list[str] = []
    if min_activation is not None and rate < min_activation:
        reasons.append(f"activation {rate:.3f} < required {min_activation:.3f}")
    return ActivationReport(
        skill=trig.name,
        activated=activated,
        prompts=n,
        rate=rate,
        passed=min_activation is None or rate >= min_activation,
        gated=min_activation is not None,
        reasons=reasons,
        misses=misses,
        why=why,
    )


def run_activation(
    plugin_dir: Path,
    run_fn: Runner,
    *,
    skills: list[str] | None = None,
    workdir: Path | None = None,
    min_activation: float | None = None,
    ask_why: Callable[[str, str], str] | None = None,
    workspace_factory: Callable[[], Path] | None = None,
) -> list[ActivationReport]:
    """Measure unprompted skill activation for the on-listing skills (optionally a subset).

    ``run_fn`` must run a REAL Claude Code session with the plugin loaded and return its transcript
    (see the CLI). ``min_activation`` gates when given; omit it to measure without a verdict — the
    intended first use, since no baseline exists yet (ADR 0088)."""
    work = workdir or plugin_dir
    triggers = [t for t in load_triggers(plugin_dir) if skills is None or t.name in skills]
    return [
        activation_rate(
            t, run_fn, work, target=t.name, min_activation=min_activation, ask_why=ask_why,
            workspace_factory=workspace_factory,
        )
        for t in triggers
    ]
