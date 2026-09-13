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

The verdict is POOLED (:func:`pooled`): activated over prompts across the whole run, one binomial.
A skill has 4-9 prompts, and at that n a per-skill floor either flakes on a healthy plugin or misses
a real drop — at a true 0.93, a per-skill floor of 0.6 fails some skill in one run of seven, and a
skill really at 0.6 gets flagged about a third of the time. Pooled over 84 prompts the same true
rate sits four sigma above a 0.80 floor, and the note-off regime (0.571, ADR 0092) fails with
certainty. The per-skill lines stay as the lens; the gate is one number (ADR 0093).
``run_activation`` reports; ``pooled`` gates when a floor is given and measures when none is.
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
from agentic_forge.gate import MAX_UNDETERMINED
from agentic_forge.tier1_runner import SkillTrigger, load_triggers

__all__ = [
    "ActivationReport",
    "NO_SESSION",
    "FIXTURE_REPO",
    "FIXTURE_DOCS",
    "prepare_workspace",
    "WHY_PROMPT",
    "WHY_BUCKETS",
    "HIT",
    "MISS",
    "COLLIDED",
    "skill_call",
    "skill_invoked",
    "session_id_of",
    "session_ran",
    "session_error",
    "MAX_UNDETERMINED",
    "bucket_why",
    "activation_rate",
    "run_activation",
    "Pooled",
    "pooled",
]

# What a transcript's `Skill` calls say about the target (see `skill_call`).
HIT = "hit"
MISS = "miss"
COLLIDED = "collided"


def skill_call(stream: str, target: str, *, builtins: frozenset[str] = frozenset()) -> str:
    """What the transcript ``stream``'s ``Skill`` tool calls say about ``target``: :data:`HIT` when
    one names it — bare or namespaced (``agentic-forge:x`` matches target ``x``); :data:`COLLIDED`
    when the only matching call is BARE and ``builtins`` owns that name too; :data:`MISS` otherwise.

    Scans every JSON object in the stream (one per line for ``--output-format stream-json``, or a
    single ``--output-format json`` envelope) for an assistant ``tool_use`` block whose tool is
    ``Skill``. A skill the model merely *names in prose* does not count: it must be an actual tool
    call, because acting-vs-routing is the whole point (ADR 0088).

    A bare ``Skill(code-review)`` in a live session is Claude Code's built-in of that name — plugin
    skills are namespaced there — so it is not a hit for ours; and it is not "did the work by hand"
    either, so it is not a miss to be asked why. A third outcome, reported as such (eval audit,
    M6). A scorer guard, not a baseline correction: the live probe showed the model calling
    ``agentic-forge:code-review`` and ``agentic-forge:security-review`` namespaced."""
    bare = target.split(":")[-1]
    collided = False
    for obj in _objects(stream):
        for block in _tool_use_blocks(obj):
            if block.get("name") != "Skill":
                continue
            inp = block.get("input") or {}
            named = str(inp.get("skill") or inp.get("name") or inp.get("command") or "")
            if named.split(":")[-1] != bare:
                continue
            if ":" in named or bare not in builtins:
                return HIT
            collided = True  # a bare call on a name a built-in owns too: whose is not knowable
    return COLLIDED if collided else MISS


def skill_invoked(stream: str, target: str, *, builtins: frozenset[str] = frozenset()) -> bool:
    """True if the transcript ``stream`` contains a ``Skill`` tool call naming ``target`` — see
    :func:`skill_call`; a bare call on a name in ``builtins`` is not one."""
    return skill_call(stream, target, builtins=builtins) == HIT


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
    # Audit C6b: a seeded vault (root MOC + two decisions, validate_vault-clean), so the
    # `knowledge` recall prompts ("have we decided on an auth approach? check our notes") have
    # notes to check instead of an absent docs/knowledge/.
    "eval/fixtures/activation/knowledge/MOC.md": "docs/knowledge/MOC.md",
    "eval/fixtures/activation/knowledge/task-priority-ordering.md": (
        "docs/knowledge/task-priority-ordering.md"
    ),
    "eval/fixtures/activation/knowledge/auth-approach.md": "docs/knowledge/auth-approach.md",
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


def session_ran(stream: str) -> bool:
    """True if the session got at least one assistant turn. A transcript without one — a usage
    limit, an auth error, a crash, a timeout before the first token — is neither a hit nor a miss:
    the model never decided anything, and counting it as a miss once read a usage limit as
    `research` at 0.200 (ADR 0093)."""
    return any(obj.get("type") == "assistant" for obj in _objects(stream))


def session_error(stream: str) -> str:
    """What a session that never ran said, for the report: its ``result`` text, else a marker."""
    for obj in _objects(stream):
        if obj.get("type") == "result":
            text = obj.get("result") or obj.get("error") or obj.get("subtype") or ""
            return " ".join(str(text).split())[:120] or "<empty result>"
    return "<no transcript>"


def session_id_of(stream: str) -> str | None:
    """The session id a stream-json transcript was recorded under (from its `init` object), so a
    miss can be asked, in the same session, why it did the work by hand (ADR 0090)."""
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
    """One skill's Tier-1b result: how often a live session reached for it unprompted. A lens,
    not a verdict — the gate is :func:`pooled` (ADR 0093)."""

    skill: str
    activated: int
    prompts: int  # asked; the rate's denominator is `determined` (prompts whose session ran)
    rate: float
    misses: list[str] = field(default_factory=list)  # prompts where the skill was NOT invoked
    why: list[tuple[str, str]] = field(default_factory=list)  # (prompt, stated reason) per miss
    undetermined: list[tuple[str, str]] = field(default_factory=list)  # (prompt, error): never ran
    collided: list[str] = field(default_factory=list)  # a bare Skill call a built-in owns too (M6)

    @property
    def determined(self) -> int:
        return self.prompts - len(self.undetermined)

    def summary_line(self) -> str:
        dead = f"; {len(self.undetermined)} never ran" if self.undetermined else ""
        bare = f"; {len(self.collided)} bare-collided" if self.collided else ""
        frac = f"({self.activated}/{self.determined}{dead}{bare})"
        return f"[{self.skill}] activation={self.rate:.3f} {frac}"


# When gated, a run with more than `MAX_UNDETERMINED` of its sessions never ran FAILS on that alone:
# the rate over the rest may be fine, but the run is not the measurement it claims to be. Below it,
# a stray limit hit or crash is excluded from the rate rather than read as a miss (ADR 0093). The
# number now lives in `gate` — every tier applies it — and is re-exported here.


@dataclass
class Pooled:
    """The run's verdict: activated over prompts, across every skill measured (ADR 0093)."""

    activated: int
    prompts: int  # asked
    undetermined: int  # never ran: excluded from the rate, capped by MAX_UNDETERMINED when gated
    rate: float  # activated / determined
    mean_of_rates: float  # each skill weighed once — printed beside the pooled rate, never gated
    skills: int
    passed: bool
    gated: bool = False  # False when run as a pure measurement (no floor) — ADR 0088
    reasons: list[str] = field(default_factory=list)
    collided: int = 0  # bare Skill calls on a name a built-in owns too: not hits, not misses (M6)

    @property
    def determined(self) -> int:
        return self.prompts - self.undetermined

    def summary_line(self) -> str:
        status = "----" if not self.gated else ("PASS" if self.passed else "FAIL")
        suffix = "  (" + "; ".join(self.reasons) + ")" if self.reasons else ""
        dead = f", {self.undetermined} of {self.prompts} never ran" if self.undetermined else ""
        bare = f", {self.collided} bare-collided" if self.collided else ""
        return (
            f"pooled {status}  activation={self.rate:.3f} ({self.activated}/{self.determined} over "
            f"{self.skills} skill(s), mean of rates {self.mean_of_rates:.3f}{dead}{bare}){suffix}"
        )


def pooled(reports: list[ActivationReport], min_activation: float | None = None) -> Pooled:
    """Pool ``reports`` into one rate and gate it when ``min_activation`` is given.

    Pooled over prompts, not averaged over skills: it is the binomial the floor's flake and power
    were computed on (ADR 0093). Sessions that never ran are left out of the rate; when gated, more
    than :data:`MAX_UNDETERMINED` of them fails the run on that alone. Nothing measured pools to
    0/0 = 0.0, so a gated run that measured nothing fails rather than passing on an empty list."""
    activated = sum(r.activated for r in reports)
    prompts = sum(r.prompts for r in reports)
    dead = sum(len(r.undetermined) for r in reports)
    determined = prompts - dead
    rate = activated / determined if determined else 0.0
    mean = sum(r.rate for r in reports) / len(reports) if reports else 0.0
    reasons: list[str] = []
    if min_activation is not None:
        if rate < min_activation:
            reasons.append(f"pooled activation {rate:.3f} < required {min_activation:.3f}")
        if prompts and dead / prompts > MAX_UNDETERMINED:
            reasons.append(
                f"{dead} of {prompts} sessions never ran (> {MAX_UNDETERMINED:.0%}): "
                "the run failed, not the plugin"
            )
    return Pooled(
        activated=activated, prompts=prompts, undetermined=dead, rate=rate, mean_of_rates=mean,
        skills=len(reports), passed=not reasons, gated=min_activation is not None, reasons=reasons,
        collided=sum(len(r.collided) for r in reports),
    )


# The reason recorded for a miss that cannot be asked: no session id in its transcript, so it
# never started or was cut off (a timeout) before its init line. A miss must never be silent —
# two of these once passed as `research` misses with no explanation (ADR 0093).
NO_SESSION = "<no session id in the transcript: the session did not start, or was cut off early>"


def activation_rate(
    trig: SkillTrigger,
    run_fn: Runner,
    workdir: Path,
    *,
    target: str,
    ask_why: Callable[[str, str], str] | None = None,
    namespace: str = "agentic-forge",
    workspace_factory: Callable[[], Path] | None = None,
    builtins: frozenset[str] = frozenset(),
) -> ActivationReport:
    """Fraction of ``trig``'s should_trigger prompts on which a live session invoked the skill.

    ``ask_why(session_id, question)`` — when given — is called for every miss whose transcript has
    a session id, with :data:`WHY_PROMPT` filled in; the answer is kept beside the prompt. A miss
    with no session id is kept too, with :data:`NO_SESSION` as its reason. A session that never
    got a turn (:func:`session_ran`) is ``undetermined``: out of the rate, listed with its error.
    A bare ``Skill`` call on a name in ``builtins`` (Claude Code's own ``code-review``,
    ``security-review``) is ``collided`` (:func:`skill_call`): in the denominator, not a hit, not
    a miss to be asked why — listed so the collision stays visible."""
    activated = 0
    misses: list[str] = []
    why: list[tuple[str, str]] = []
    undetermined: list[tuple[str, str]] = []
    collided: list[str] = []
    for prompt in trig.should_trigger:
        cwd = workspace_factory() if workspace_factory else workdir
        stream = run_fn("", prompt, cwd)
        outcome = skill_call(stream, target, builtins=builtins)
        if outcome == HIT:
            activated += 1
            continue
        if outcome == COLLIDED:
            collided.append(prompt)
            continue
        if not session_ran(stream):
            undetermined.append((prompt, session_error(stream)))
            continue
        misses.append(prompt)
        if ask_why is None:
            continue
        sid = session_id_of(stream)
        if not sid:
            why.append((prompt, NO_SESSION))
            continue
        question = WHY_PROMPT.format(namespace=namespace, skill=trig.name)
        try:
            why.append((prompt, ask_why(sid, question).strip()))
        except Exception as exc:  # noqa: BLE001 — a lost follow-up must not lose the measurement
            why.append((prompt, f"<follow-up failed: {type(exc).__name__}>"))
    n = len(trig.should_trigger)
    determined = n - len(undetermined)
    return ActivationReport(
        skill=trig.name, activated=activated, prompts=n,
        rate=activated / determined if determined else 0.0,
        misses=misses, why=why, undetermined=undetermined, collided=collided,
    )


def run_activation(
    plugin_dir: Path,
    run_fn: Runner,
    *,
    skills: list[str] | None = None,
    workdir: Path | None = None,
    ask_why: Callable[[str, str], str] | None = None,
    workspace_factory: Callable[[], Path] | None = None,
    builtins: frozenset[str] = frozenset(),
) -> list[ActivationReport]:
    """Measure unprompted skill activation for the on-listing skills (optionally a subset).

    ``run_fn`` must run a REAL Claude Code session with the plugin loaded and return its transcript
    (see the CLI). One report per skill, a lens each; the verdict is :func:`pooled` over them
    (ADR 0093) — or no verdict at all, the measurement the first runs were (ADR 0088).
    ``builtins`` are the skill names Claude Code itself owns (the CLI loads them from the fixture
    ``tier1_runner.load_extra_listing`` reads), so a bare call on one is scored as a collision."""
    work = workdir or plugin_dir
    triggers = [t for t in load_triggers(plugin_dir) if skills is None or t.name in skills]
    return [
        activation_rate(
            t, run_fn, work, target=t.name, ask_why=ask_why, workspace_factory=workspace_factory,
            builtins=builtins,
        )
        for t in triggers
    ]
