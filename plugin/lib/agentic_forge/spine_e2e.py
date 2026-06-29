"""Tier-3 end-to-end scenarios (the SDLC spine + the Stage 4-6 domain chains).

The **spine** scenario carries one feature (`task-priorities`) through all six phases
(`research -> product -> architecture -> plan -> develop -> code-review`) on an isolated copy of
the taskstore fixture, checking per-phase handoff artifacts and that the implemented code passes
the repo's tests. The **domain** scenarios (`quality-gate`, `ops-incident`, …) chain the Stage 4-6
skills the same way, with deterministic per-phase checkpoints (see docs/architecture/domain-e2e.md,
ADR 0030).

The model/agent call is a seam (:data:`agent_eval.Runner`) so the orchestration + checkpoints are
unit-tested with stubs; the real run drives each phase with the `claude` CLI. Checkpoints never
call an LLM judge: each is a code comparison, a substring/location match on the model's artifact,
or a schema-only validation of a handoff gated elsewhere.

Fidelity note: in this environment the plugin's subagents are not registered, so each phase is
approximated as a single CLI call seeded with the phase skill's body (rather than the skill
forking its roles). The checkpoints validate the *artifacts and code*. The spine repo's test
command is the **Python toolchain hardcoded for this fixture** (``python -m pytest``); a non-Python
E2E would drive it from ``stacks.primary(repo).toolchain.test`` instead.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import handoff, ops, release, vault
from .agent_eval import Runner
from .frontmatter import parse as parse_frontmatter
from .gate import all_passed

__all__ = [
    "FEATURE_SLUG",
    "FIXTURE_REPO",
    "PRD",
    "PLAN",
    "PHASES",
    "Checkpoint",
    "PhaseResult",
    "check_architecture",
    "repo_tests_pass",
    "check_develop",
    "check_code_review",
    "check_research",
    "check_product",
    "check_plan",
    "check_test_strategy",
    "check_security_review",
    "expected_release_version",
    "check_release",
    "check_deploy_status",
    "check_incident",
    "check_onboarding",
    "check_ux_spec",
    "check_market_brief",
    "CHECKS",
    "skill_body",
    "SeedItem",
    "Phase",
    "Scenario",
    "prepare_scenario",
    "run_scenario",
    "SPINE",
    "SCENARIOS",
    "all_passed",
    "scenario_wiring",
]

FEATURE_SLUG = "task-priorities"
FIXTURE_REPO = "eval/fixtures/spine/target-repo"
PRD = "eval/fixtures/spine/prd.md"
PLAN = "eval/fixtures/spine/plan.md"
PHASES = ("research", "product", "architecture", "plan", "develop", "code-review")

_SEMVER = re.compile(r"^v?\d+\.\d+\.\d+$")


@dataclass
class Checkpoint:
    name: str
    passed: bool
    detail: str = ""

    def __str__(self) -> str:
        mark = "ok " if self.passed else "FAIL"
        suffix = f" — {self.detail}" if self.detail else ""
        return f"  [{mark}] {self.name}{suffix}"


@dataclass
class PhaseResult:
    phase: str
    checkpoints: list[Checkpoint] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.checkpoints) and all(c.passed for c in self.checkpoints)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _commit(repo: Path, message: str, *, allow_empty: bool = False) -> None:
    args = ["-c", "user.email=e2e@local", "-c", "user.name=e2e", "commit", "-q", "-m", message]
    if allow_empty:
        args.insert(-2, "--allow-empty")
    _git(repo, *args)


def _copy_fixture(plugin_dir: Path, repo: Path, fixture: str | None) -> None:
    """(Re)create ``repo`` from ``fixture`` (a fixture dir relative to the plugin), or empty."""
    if repo.exists():  # allow re-running against the same --workspace (a natural debugging move)
        shutil.rmtree(repo)
    if fixture:
        shutil.copytree(plugin_dir / fixture, repo)
    else:
        repo.mkdir(parents=True)


def _valid(path: Path, artifact_type: str) -> bool:
    try:
        handoff.load_artifact(path, expected_type=artifact_type)
        return True
    except handoff.HandoffError:
        return False


def _load(path: Path, artifact_type: str) -> handoff.Artifact | None:
    """Load + validate an artifact, or return None if missing/invalid (for richer checkpoints)."""
    try:
        return handoff.load_artifact(path, expected_type=artifact_type)
    except handoff.HandoffError:
        return None


def _sdlc(repo: Path, slug: str) -> Path:
    return repo / "docs" / "sdlc" / slug


# --- spine checkpoints (slug defaults to the spine feature, so the spine guard is unchanged) ---


def check_architecture(repo: Path, slug: str = FEATURE_SLUG) -> list[Checkpoint]:
    sdlc = _sdlc(repo, slug)
    td = sdlc / "tech-design.md"
    adrs = sorted(sdlc.glob("adr-*.md"))
    return [
        Checkpoint(
            "tech-design.md exists and validates", td.is_file() and _valid(td, "tech-design")
        ),
        Checkpoint("at least one ADR", len(adrs) >= 1, f"{len(adrs)} ADR(s)"),
    ]


def repo_tests_pass(repo: Path) -> bool:
    result = subprocess.run(
        # sys.executable (not "python") so the nested run uses the same interpreter — portable.
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def check_develop(repo: Path, *, run_tests: bool = True) -> list[Checkpoint]:
    src = repo / "taskstore.py"
    raw = src.read_text(encoding="utf-8") if src.is_file() else ""
    # An implementation marker, not a bare mention — the baseline docstring says "no notion of
    # priority", which must NOT count. Comment-only lines are dropped so a `# priority=` TODO
    # can't satisfy the marker either; it must appear in actual code.
    code = "\n".join(ln for ln in raw.splitlines() if not ln.lstrip().startswith("#")).lower()
    has_priority = any(m in code for m in ("priority=", "priority:", ".priority"))
    cps = [Checkpoint("priority implemented in taskstore", has_priority)]
    if run_tests:
        cps.append(Checkpoint("repo test suite passes", repo_tests_pass(repo)))
    return cps


def check_code_review(repo: Path, slug: str = FEATURE_SLUG) -> list[Checkpoint]:
    rv = _sdlc(repo, slug) / "review.md"
    valid = rv.is_file() and _valid(rv, "review")
    cps = [Checkpoint("review.md exists and validates", valid)]
    if valid:
        verdict = handoff.load_artifact(rv, expected_type="review").header.get("verdict")
        cps.append(Checkpoint("verdict present", verdict in handoff.VERDICTS, str(verdict)))
    return cps


def _artifact_checkpoint(
    repo: Path, filename: str, artifact_type: str, slug: str = FEATURE_SLUG
) -> Checkpoint:
    path = _sdlc(repo, slug) / filename
    ok = path.is_file() and _valid(path, artifact_type)
    return Checkpoint(f"{filename} exists and validates", ok)


def check_research(repo: Path, slug: str = FEATURE_SLUG) -> list[Checkpoint]:
    return [_artifact_checkpoint(repo, "research-brief.md", "research-brief", slug)]


def check_product(repo: Path, slug: str = FEATURE_SLUG) -> list[Checkpoint]:
    return [_artifact_checkpoint(repo, "prd.md", "prd", slug)]


def check_plan(repo: Path, slug: str = FEATURE_SLUG) -> list[Checkpoint]:
    return [_artifact_checkpoint(repo, "plan.md", "plan", slug)]


# --- domain checkpoints (Stage 4-6; deterministic — no LLM judge) ---


def check_test_strategy(
    repo: Path, slug: str, *, risk_keywords: tuple[str, ...] = ()
) -> list[Checkpoint]:
    art = _load(_sdlc(repo, slug) / "test-strategy.md", "test-strategy")
    cps = [Checkpoint("test-strategy.md valid", art is not None)]
    if art is not None:
        levels = art.header.get("test_levels") or []
        cps.append(Checkpoint("test_levels non-empty", bool(levels), f"{len(levels)} level(s)"))
        if risk_keywords:  # schema does not enforce `risks`, so assert a known risk is referenced
            blob = (str(art.header.get("risks", "")) + "\n" + art.body).lower()
            cps.append(
                Checkpoint("risk area referenced", any(k.lower() in blob for k in risk_keywords))
            )
    return cps


def check_security_review(
    repo: Path,
    slug: str,
    *,
    filename: str = "security-review.md",
    sink_markers: tuple[str, ...] = (),
) -> list[Checkpoint]:
    art = _load(_sdlc(repo, slug) / filename, "review")
    cps = [Checkpoint(f"{filename} valid review", art is not None)]
    if art is not None and sink_markers:
        findings = art.header.get("findings") or []
        locs = " ".join(
            str(f.get("location", "")) + " " + str(f.get("issue", ""))
            for f in findings
            if isinstance(f, dict)
        )
        blob = (locs + " " + art.body).lower()
        cps.append(
            Checkpoint(
                "planted sink referenced", any(m.lower() in blob for m in sink_markers)
            )
        )
    return cps


def expected_release_version(repo: Path, baseline: str, tag: str) -> str | None:
    """Compute the release bump from the commits since ``tag`` (real git history), or None when
    there are none. Independent truth for the release checkpoint, unit-tested against a built
    git repo."""
    messages = release.commits_since(repo, tag)
    return release.summarize(baseline, messages).version if messages else None


def check_release(
    repo: Path, slug: str, *, expected_version: str | None = None
) -> list[Checkpoint]:
    art = _load(_sdlc(repo, slug) / "release.md", "release")
    cps = [Checkpoint("release.md valid", art is not None)]
    if art is not None:
        version = str(art.header.get("version", ""))
        if expected_version is not None:
            cps.append(
                Checkpoint(
                    "version == computed bump",
                    version == expected_version,
                    f"{version} vs {expected_version}",
                )
            )
        else:
            cps.append(Checkpoint("version is semver", bool(_SEMVER.match(version)), version))
        cps.append(Checkpoint("changelog non-empty", bool(art.header.get("changelog"))))
    return cps


def check_deploy_status(repo: Path, slug: str, *, expected_health: str) -> list[Checkpoint]:
    art = _load(_sdlc(repo, slug) / "deploy-status.md", "deploy-status")
    cps = [Checkpoint("deploy-status.md valid", art is not None)]
    if art is not None:  # health lives in the `pipeline` field, not a `health` key (ADR 0030)
        pipeline = art.header.get("pipeline")
        cps.append(
            Checkpoint(
                f"pipeline == {expected_health}", pipeline == expected_health, str(pipeline)
            )
        )
    return cps


def check_incident(
    repo: Path, slug: str, *, expected_sev: str, env_marker: str | None = None
) -> list[Checkpoint]:
    art = _load(_sdlc(repo, slug) / "incident.md", "incident")
    cps = [Checkpoint("incident.md valid", art is not None)]
    if art is not None:
        sev = art.header.get("severity")
        cps.append(Checkpoint(f"severity == {expected_sev}", sev == expected_sev, str(sev)))
        if env_marker:  # handoff: the incident must reference the failing environment
            blob = (str(art.header.get("impact", "")) + " " + art.body).lower()
            cps.append(Checkpoint(f"references {env_marker}", env_marker.lower() in blob))
    return cps


def check_onboarding(repo: Path, slug: str) -> list[Checkpoint]:
    art = _load(_sdlc(repo, slug) / "onboarding.md", "onboarding")
    problems = vault.validate_vault(repo)  # vault seeded from the codebase must be link-clean
    return [
        Checkpoint("onboarding.md valid", art is not None),
        Checkpoint("vault validates clean", not problems, "; ".join(problems[:2])),
    ]


def check_ux_spec(repo: Path, slug: str) -> list[Checkpoint]:
    art = _load(_sdlc(repo, slug) / "ux-spec.md", "ux-spec")
    cps = [Checkpoint("ux-spec.md valid", art is not None)]
    if art is not None:
        cps.append(Checkpoint("flows non-empty", bool(art.header.get("flows"))))
        # the schema does not enforce `accessibility`, so assert it here
        cps.append(Checkpoint("accessibility non-empty", bool(art.header.get("accessibility"))))
    return cps


def check_market_brief(
    repo: Path, slug: str, *, competitors: tuple[str, ...] = ()
) -> list[Checkpoint]:
    art = _load(_sdlc(repo, slug) / "market-brief.md", "market-brief")
    cps = [Checkpoint("market-brief.md valid", art is not None)]
    if art is not None and competitors:
        blob = (str(art.header.get("competitors", "")) + " " + art.body).lower()
        missing = [c for c in competitors if c.lower() not in blob]
        detail = f"missing {missing}" if missing else ""
        cps.append(Checkpoint("named competitors present", not missing, detail))
    return cps


CHECKS: dict[str, Callable[[Path], list[Checkpoint]]] = {
    "research": check_research,
    "product": check_product,
    "architecture": check_architecture,
    "plan": check_plan,
    "develop": check_develop,
    "code-review": check_code_review,
}


def skill_body(plugin_dir: Path, name: str) -> str:
    text = (plugin_dir / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    _, body = parse_frontmatter(text)
    return body.strip()


def _phase_prompt(phase: str) -> str:
    sdlc = f"docs/sdlc/{FEATURE_SLUG}/"
    prompts = {
        "research": (
            f"Your working directory is a checkout of the target repo. Read FEATURE_REQUEST.md and "
            f"the code, research the feature (prior art / options / feasibility), and write "
            f"{sdlc}research-brief.md (frontmatter type: research-brief, feature, status, date, "
            "sources[]) with synthesized findings and a recommendation. No code changes."
        ),
        "product": (
            f"Read {sdlc}research-brief.md and the code. Write the product spec to {sdlc}prd.md "
            "(frontmatter type: prd, feature, status, goals[], non_goals[], metrics[], "
            "acceptance[]) with user stories. Requirements only — no design or code."
        ),
        "architecture": (
            f"Read {sdlc}prd.md and the code, and produce the technical design: write "
            f"{sdlc}tech-design.md (frontmatter type: tech-design, feature, status, decisions, "
            "components, risks) and at least one adr-*.md (Context/Decision/Alternatives/"
            "Consequences) in that directory. Design only — no code changes."
        ),
        "plan": (
            f"Read {sdlc}tech-design.md. Write the work plan to {sdlc}plan.md (frontmatter "
            "type: plan, feature, status, tasks[] with id+deps, checkpoints[], deferred[]). "
            "A plan only — no code."
        ),
        "develop": (
            f"Read {sdlc}plan.md and {sdlc}tech-design.md. Implement the feature in taskstore.py "
            "(priority on add(); list() sorted by priority; preserve existing behavior) and add "
            "tests to test_taskstore.py. Run `python -m pytest -q` and make the whole suite green. "
            "Stay within this working directory."
        ),
        "code-review": (
            f"Review the change to taskstore.py / test_taskstore.py (run `git diff`). Write a "
            f"verdict to {sdlc}review.md with frontmatter: type: review, target, iteration: 1, "
            "verdict (approve|changes), findings[]. Do not modify the code."
        ),
    }
    return prompts[phase]


# --- scenario model -----------------------------------------------------------


@dataclass(frozen=True)
class SeedItem:
    """A fixture file to pre-place in the workspace: ``src`` (relative to the plugin) -> ``dest``
    (relative to the repo root) — supports arbitrary destinations, not only ``docs/sdlc/``."""

    src: str
    dest: str


@dataclass(frozen=True)
class Phase:
    """One scenario phase: the skill whose body seeds the run, the instruction, and the
    deterministic checkpoint(s) evaluated after it."""

    skill: str
    prompt: str
    checks: Callable[[Path], list[Checkpoint]]


@dataclass(frozen=True)
class Scenario:
    """A Tier-3 scenario: a chain of phases on an isolated workspace, with deterministic
    checkpoints. ``fixture`` is the repo to copy (None = an empty workspace); ``seed`` pre-places
    inputs; ``tag`` creates a baseline tag (for ``release``); ``commits`` replays conventional
    commits after the tag so a release bump is reproducible."""

    name: str
    slug: str
    phases: tuple[Phase, ...]
    fixture: str | None = FIXTURE_REPO
    seed: tuple[SeedItem, ...] = ()
    tag: str | None = None
    commits: tuple[str, ...] = ()


def prepare_scenario(plugin_dir: Path, dest: Path, scenario: Scenario) -> Path:
    """Materialize a scenario's isolated workspace: copy the fixture, seed inputs, git-init +
    baseline commit, optionally tag and replay conventional commits."""
    repo = dest / "repo"
    _copy_fixture(plugin_dir, repo, scenario.fixture)
    for item in scenario.seed:
        target = repo / item.dest
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((plugin_dir / item.src).read_text(encoding="utf-8"), encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _commit(repo, "baseline")
    if scenario.tag:
        _git(repo, "tag", scenario.tag)
    for msg in scenario.commits:
        _commit(repo, msg, allow_empty=True)
    return repo


def _run_phase_with_retry(
    plugin_dir: Path, phase: Phase, repo: Path, run_phase: Runner, retries: int
) -> PhaseResult:
    """Run a phase, re-running it up to ``retries`` more times if its checkpoints fail — this
    retries the **model** (a fresh attempt at the same prompt), never relaxing a checkpoint, so a
    one-off invalid artifact (model frontmatter variance) self-corrects. Returns the first passing
    attempt, or the last one."""
    body = skill_body(plugin_dir, phase.skill)
    attempt = 0
    while True:
        run_phase(body, phase.prompt, repo)
        result = PhaseResult(phase.skill, phase.checks(repo))
        if result.passed or attempt >= retries:
            return result
        attempt += 1


def run_scenario(
    plugin_dir: Path,
    scenario: Scenario,
    *,
    run_phase: Runner,
    workspace: Path,
    retries: int = 1,
) -> list[PhaseResult]:
    """Run a scenario's phases in an isolated copy and return per-phase checkpoint results. Each
    phase is retried up to ``retries`` times if its checkpoints fail (``retries=0`` disables it)."""
    repo = prepare_scenario(plugin_dir, workspace, scenario)
    return [
        _run_phase_with_retry(plugin_dir, phase, repo, run_phase, retries)
        for phase in scenario.phases
    ]


# --- scenario registry --------------------------------------------------------

SPINE = Scenario(
    name="spine",
    slug=FEATURE_SLUG,
    fixture=FIXTURE_REPO,
    phases=tuple(Phase(skill=ph, prompt=_phase_prompt(ph), checks=CHECKS[ph]) for ph in PHASES),
)


def _quality_gate() -> Scenario:
    slug = FEATURE_SLUG
    sdlc = f"docs/sdlc/{slug}/"
    base = "1.0.0"
    tag = f"v{base}"
    return Scenario(
        name="quality-gate",
        slug=slug,
        fixture=FIXTURE_REPO,
        tag=tag,
        # Conventional commits replayed after the baseline tag so the release bump is reproducible.
        commits=("feat: add task priority", "fix: clamp invalid priority"),
        seed=(
            SeedItem(PRD, f"{sdlc}prd.md"),
            SeedItem("eval/fixtures/spine/tech-design.md", f"{sdlc}tech-design.md"),
            # Isolated, un-imported planted defect (a SQLi sink) — keeps the test suite green.
            SeedItem("eval/fixtures/security-engineer/case1-sqli.py", "user_lookup.py"),
        ),
        phases=(
            Phase(
                "qa-test-strategy",
                f"Read {sdlc}prd.md and {sdlc}tech-design.md and the code. Plan the tests for the "
                f"priority feature and write {sdlc}test-strategy.md (frontmatter type: "
                "test-strategy, feature, status, test_levels[], risks[], cases[]). No code.",
                lambda repo: check_test_strategy(
                    repo, slug, risk_keywords=("priorit", "invalid", "order")
                ),
            ),
            Phase("develop", _phase_prompt("develop"), check_develop),
            Phase(
                "security-review",
                f"Run a security review of user_lookup.py and the diff. Write {sdlc}"
                "security-review.md (frontmatter type: review, target, iteration: 1, verdict, "
                "findings[] each with severity+location). Reference the exact vulnerable location. "
                "Do not modify code.",
                lambda repo: check_security_review(
                    repo, slug, sink_markers=("user_lookup", "find_user", "sql", "injection")
                ),
            ),
            Phase("code-review", _phase_prompt("code-review"), check_code_review),
            Phase(
                "release",
                f"Decide the next version from the commits since {tag} and write {sdlc}release.md "
                "(frontmatter type: release, feature, status, version, changelog[], breaking[]). "
                "Aggregate the whole release's changelog.",
                lambda repo: check_release(
                    repo, slug, expected_version=expected_release_version(repo, base, tag)
                ),
            ),
        ),
    )


def _ops_incident() -> Scenario:
    slug = "checkout-outage"
    sdlc = f"docs/sdlc/{slug}/"
    sev1 = ops.classify_incident(outage=True)  # deterministic expected severity
    return Scenario(
        name="ops-incident",
        slug=slug,
        fixture=None,  # artifact-driven; no app repo for phases 1-2
        seed=(
            SeedItem("eval/fixtures/deploy-watch/prod-failing.json", "pipeline.json"),
            SeedItem("eval/fixtures/incident-response/outage-scenario.md", "outage-scenario.md"),
        ),
        phases=(
            Phase(
                "deploy-watch",
                "Read pipeline.json and load it into ops.InMemoryPipeline / ops.InMemoryAlerts — "
                "do NOT use a live connector (ignore any gh CLI or GRAFANA_URL). Assess rollout "
                f"health and write {sdlc}deploy-status.md (frontmatter type: deploy-status, "
                "environment, pipeline, deploys[], alerts, action).",
                lambda repo: check_deploy_status(repo, slug, expected_health="failing"),
            ),
            Phase(
                "incident-response",
                "Read outage-scenario.md and the deploy-watch output "
                f"{sdlc}deploy-status.md. Classify severity with ops.classify_incident "
                f"and write {sdlc}incident.md (frontmatter type: incident, severity, "
                "status, impact, timeline[], remediation[]); name the impacted environment "
                "from the deploy-status in the impact.",
                lambda repo: check_incident(
                    repo, slug, expected_sev=sev1, env_marker="production"
                ),
            ),
            Phase(
                "release",
                f"Cut the hotfix release for the rollback. Write {sdlc}release.md with YAML "
                "frontmatter containing ALL of: type: release, feature, status, version (a semver "
                "string such as 1.4.3), and a non-empty changelog list (e.g. '- Fixed: roll back "
                "the failing deploy').",
                lambda repo: check_release(repo, slug, expected_version=None),  # schema-only
            ),
        ),
    )


def _product_inception() -> Scenario:
    slug = "newapp-onboarding"
    sdlc = f"docs/sdlc/{slug}/"
    return Scenario(
        name="product-inception",
        slug=slug,
        fixture=None,  # the onboarded codebase is seeded at the repo root
        seed=(
            SeedItem("eval/fixtures/repo-onboarding/app.py", "app.py"),
            SeedItem("eval/fixtures/repo-onboarding/worker.py", "worker.py"),
            SeedItem("eval/fixtures/repo-onboarding/README.md", "README.md"),
        ),
        phases=(
            Phase(
                "repo-onboarding",
                "Analyze this codebase (app.py, worker.py, README.md): map components, entry "
                f"points, conventions, and risks and write {sdlc}onboarding.md (frontmatter type: "
                "onboarding, feature, status, components[], entry_points[], conventions[], "
                "risks[]). Seed the knowledge vault (docs/knowledge/) with linked notes via the "
                "agentic_forge.vault helper (so it validates clean).",
                lambda repo: check_onboarding(repo, slug),
            ),
            # research/product/architecture are carriers here (their own quality is the spine
            # Tier-3) — included to exercise the onboarding -> … -> ux -> architecture handoffs.
            Phase(
                "research",
                f"Research the app's domain and write {sdlc}research-brief.md (frontmatter type: "
                "research-brief, feature, status, date, sources[]).",
                lambda repo: check_research(repo, slug),
            ),
            Phase(
                "product",
                f"Read {sdlc}research-brief.md and write {sdlc}prd.md with YAML frontmatter "
                "containing ALL of: type: prd, feature, status, a non-empty goals list, non_goals, "
                "metrics, and a non-empty acceptance list. Add user stories in the body.",
                lambda repo: check_product(repo, slug),
            ),
            Phase(
                "ux-design",
                f"Read {sdlc}prd.md and design the UX. Write {sdlc}ux-spec.md with VALID YAML "
                "frontmatter (quote any value containing a colon) holding ALL of: type: ux-spec, "
                "feature, status, a non-empty flows list, screens, a non-empty accessibility list, "
                "and design_system.",
                lambda repo: check_ux_spec(repo, slug),
            ),
            Phase(
                "architecture",
                f"Read {sdlc}prd.md and {sdlc}ux-spec.md and write {sdlc}tech-design.md with VALID "
                "YAML frontmatter (quote any value containing a colon) holding type: tech-design, "
                "feature, status, a non-empty decisions list, a non-empty components list, and "
                "risks; plus at least one adr-*.md.",
                lambda repo: check_architecture(repo, slug),
            ),
        ),
    )


def _market_brief() -> Scenario:
    slug = "search-gtm"
    sdlc = f"docs/sdlc/{slug}/"
    return Scenario(
        name="market-brief",
        slug=slug,
        fixture=None,
        seed=(SeedItem("eval/fixtures/marketing/market-notes.md", "market-notes.md"),),
        phases=(
            Phase(
                "marketing",
                f"Read market-notes.md and write {sdlc}market-brief.md (frontmatter type: "
                "market-brief, feature, status, segments[], competitors[], sizing, sources[]). "
                "Name the competitors from the notes, cite sources, and do not fabricate figures.",
                lambda repo: check_market_brief(
                    repo, slug, competitors=("Algolia", "Elastic", "Typesense")
                ),
            ),
        ),
    )


SCENARIOS: dict[str, Scenario] = {
    "spine": SPINE,
    "quality-gate": _quality_gate(),
    "ops-incident": _ops_incident(),
    "product-inception": _product_inception(),
    "market-brief": _market_brief(),
}


def scenario_wiring(plugin_dir: Path, scenario: Scenario) -> list[str]:
    """Return a scenario's setup problems (skills present, fixture + seed sources present, and —
    for ops-incident — the in-memory/no-live-connector guard is in the deploy-watch prompt)."""
    problems: list[str] = []
    for phase in scenario.phases:
        if not (plugin_dir / "skills" / phase.skill / "SKILL.md").is_file():
            problems.append(f"{scenario.name}: missing skill: {phase.skill}")
    if scenario.fixture and not (plugin_dir / scenario.fixture).exists():
        problems.append(f"{scenario.name}: missing fixture: {scenario.fixture}")
    for item in scenario.seed:
        if not (plugin_dir / item.src).exists():
            problems.append(f"{scenario.name}: missing seed source: {item.src}")
    for phase in scenario.phases:
        if phase.skill == "deploy-watch" and "do not use a live" not in phase.prompt.lower():
            problems.append(f"{scenario.name}: deploy-watch prompt must neutralize live connectors")
    return problems
