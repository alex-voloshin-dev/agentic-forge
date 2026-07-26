"""Tier-1 trigger eval runner on LIVE skill descriptions (ADR 0016).

Build the real always-on skill listing — every **model-invocable** skill's ``name`` +
``description`` (``disable-model-invocation`` skills are off-listing and excluded) — and, for
each skill that declares ``tier1_trigger``, ask the router to classify each of its trigger
prompts against that live listing. Grading is deterministic: a ``should_trigger`` prompt must
select the skill (recall); a ``should_not_trigger`` prompt must NOT (specificity).
Each prompt's **routing rate** over N samples (default 5) is averaged into recall/specificity —
the mean per-prompt rate (ADR 0026), which absorbs router stochasticity without the majority-vote
cliff. Gated through the shared
pure functions :func:`gate.trigger_metrics` + :func:`gate.tier1_trigger` (recall/specificity
≥ 0.9 from the contract).

The model call is a seam (:data:`agent_eval.Runner` — reused so there is no second transport):
``system`` carries the router instruction + the rendered live listing, ``user`` is the trigger
prompt, and the reply is parsed to a skill name. Orchestration + grading are unit-tested with
stub runners; the real run classifies via the ``claude`` CLI (subscription) or the API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentic_forge import gate
from agentic_forge.agent_eval import DEFAULT_RUNS, Runner
from agentic_forge.evals import load_evals
from agentic_forge.frontmatter import parse as parse_frontmatter
from agentic_forge.gate import all_passed

__all__ = [
    "DEFAULT_RUNS",
    "SkillCard",
    "SkillTrigger",
    "Tier1Report",
    "load_listing",
    "render_listing",
    "build_router_system",
    "parse_selection",
    "selection_rate",
    "load_triggers",
    "eval_skill",
    "run_tier1",
    "check_wiring",
    "all_passed",
    "INVALID",
    "MAX_ANSWER_TOKENS",
    "PromptRate",
]

# A reply that is not a router answer at all. Distinct from ``"none"`` (a real routing decision:
# "no skill fits"), because scoring a non-answer as a decision is silent data corruption — see
# :func:`parse_selection` and ADR 0064.
INVALID = "invalid"

# Longest reply still treated as the terse answer the format demands. A conforming reply is one
# name (or `none`), sometimes wrapped in backticks or a short sentence; anything longer is prose —
# the model answering some *other* question — and must not be mined for a skill name.
# Raised from 12 (ADR 0067): natural terse answers such as "I'd route this to the `research` skill —
# it's the best match." run to 13 tokens, and rejecting those made a correctly-answering router fail
# the gate. Precision no longer rests on the count — the script, negation and acting guards below do
# that work — so this is only a coarse prose ceiling.
MAX_ANSWER_TOKENS = 16

# Hard character ceiling, applied BEFORE tokenisation — a coarse "this is prose" guard.
MAX_ANSWER_CHARS = 200

# The skill names and the answer format are English, so a reply carrying a run of non-Latin letters
# is the model doing something other than routing. This is the guard the token count CANNOT provide:
# `[a-z0-9-]+` sees no tokens at all in Cyrillic prose, so such a reply slid under MAX_ANSWER_TOKENS
# and was scored as a vote for whatever English word it happened to contain — and the reply that
# motivated ADR 0064 was Russian, so the original fix missed its own founding case (corrected by
# ADR 0067). Punctuation like an em dash is not alphabetic and does not count.
MAX_NON_LATIN_LETTERS = 8

# Words that signal the reply is reasoning ABOUT the routing rather than giving it. One of these
# next to a skill name means the sentence may be *rejecting* that skill — "…mentions research, but
# none of the skills fit" — so the reply is not a usable decision either way.
_NEGATION = frozenset(
    "but not no none neither nor however although isn t doesn don cannot can won".split()
)

# Words that mark the model CARRYING OUT the request instead of routing it ("I will analyse the
# repository and prepare a research summary…"). Such a reply names a skill innocently and carries no
# negation, so only this catches it — and it is the English twin of the non-Latin case above.
_ACTING = frozenset(
    "will ll let going start starting begin beginning proceed analyse analyze gather review "
    "reading read write writing produce producing summary".split()
)

# Ways a router declines that are not the literal token `none`. `none` remains the canonical answer;
# these are accepted as the same DECISION so a correctly-declining router is not scored as silent
# (which would drain specificity samples exactly where the router is right).
_DECLINE = re.compile(r"^\W*(none|no\s+skill|nothing|n/?a|not\s+applicable)\b")

ROUTER_INSTRUCTION = (
    "You are the skill router for Claude Code. Skills auto-load by how well their description "
    "matches the user's request. Given the available skills and a request, identify the ONE "
    "skill whose description best matches the request's intent, and reply with its name. Do not "
    "carry out the request yourself (don't write the code, do the review, etc.) — only route it. "
    "Prefer the best-matching skill; reply none only when the request genuinely fits no skill's "
    "domain."
)
ANSWER_FORMAT = (
    "Reply with exactly one skill name from the list above, or none. Output only that — do not "
    "perform the request."
)


@dataclass(frozen=True)
class SkillCard:
    """One row of the live router listing."""

    name: str
    description: str


@dataclass(frozen=True)
class SkillTrigger:
    """A skill's Tier-1 contract: its thresholds and trigger prompts."""

    name: str
    thresholds: dict[str, Any]
    should_trigger: list[str]
    should_not_trigger: list[str]
    off_listing: bool = False


@dataclass
class Tier1Report:
    skill: str
    recall: float | None
    specificity: float | None
    passed: bool
    reasons: list[str] = field(default_factory=list)
    should_trigger_rates: list[float] = field(default_factory=list)  # per-prompt routing rate
    should_not_trigger_rates: list[float] = field(default_factory=list)  # per-prompt false-fire
    invalid_calls: int = 0  # router calls that returned no decision at all (ADR 0064)
    total_calls: int = 0
    unmeasured: list[str] = field(default_factory=list)  # prompts where EVERY call was invalid

    def summary_line(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        rc = "n/a" if self.recall is None else f"{self.recall:.3f}"
        sp = "n/a" if self.specificity is None else f"{self.specificity:.3f}"
        suffix = "" if self.passed else "  (" + "; ".join(self.reasons) + ")"
        # Surface discarded calls ALWAYS, pass or fail: a green number computed from half the
        # samples is weaker evidence than one from all of them, and hiding that is a silent cap.
        noise = (
            f"  [{self.invalid_calls}/{self.total_calls} calls returned no decision]"
            if self.invalid_calls
            else ""
        )
        return f"[{self.skill}] {status}  recall={rc} specificity={sp}{noise}{suffix}"


# --- live listing ------------------------------------------------------------


def _frontmatter(md_path: Path) -> dict[str, Any]:
    fm, _ = parse_frontmatter(md_path.read_text(encoding="utf-8"))
    return fm


def _is_off_listing(fm: dict[str, Any]) -> bool:
    return str(fm.get("disable-model-invocation", "")).strip().lower() == "true"


def load_listing(plugin_dir: Path) -> list[SkillCard]:
    """The live always-on listing: model-invocable skills' name+description, sorted by name."""
    cards: list[SkillCard] = []
    skills_dir = plugin_dir / "skills"
    if not skills_dir.is_dir():
        return cards
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        md = skill_dir / "SKILL.md"
        if not md.is_file():
            continue
        fm = _frontmatter(md)
        if _is_off_listing(fm):
            continue
        name = str(fm.get("name") or skill_dir.name)
        cards.append(SkillCard(name, str(fm.get("description") or "").strip()))
    return cards


def render_listing(cards: list[SkillCard]) -> str:
    return "\n".join(f"- {c.name}: {c.description}" for c in cards)


def build_router_system(cards: list[SkillCard]) -> str:
    return f"{ROUTER_INSTRUCTION}\n\nAvailable skills:\n{render_listing(cards)}\n\n{ANSWER_FORMAT}"


# --- routing + grading -------------------------------------------------------


def parse_selection(reply: str, names: list[str]) -> str:
    """Normalize a router reply to a skill name in ``names``, ``"none"``, or :data:`INVALID`.

    Scans left to right and returns the first token that is a known skill name or the word
    ``none`` — so "research", "`research`", and "the research skill" all map to ``research``.

    **Only a reply that obeys the terse answer format is scored** (at most
    :data:`MAX_ANSWER_TOKENS` tokens). Anything longer — or a short reply naming nothing known —
    is :data:`INVALID`: the call produced no routing decision, and the caller must exclude it
    rather than count it (ADR 0064).

    Why this matters (the bug this replaces): the old version mapped *any* reply to a decision.
    An off-format answer — e.g. the model ignoring the instruction and writing a page of prose
    about the repository, which happens when ambient context primes it to act like an agent —
    was mined for the first skill-like word and scored as a routing vote. That silently turned
    "the router never answered" into "the router chose X", depressing recall while leaving
    specificity at a perfect 1.000 (prose rarely names the skill under test either). The result
    was an unstable metric that invited description edits to chase measurement noise.
    """
    text = reply.strip()
    if len(text) > MAX_ANSWER_CHARS:
        return INVALID  # prose by sheer length
    if sum(1 for ch in text if ch.isalpha() and not ch.isascii()) > MAX_NON_LATIN_LETTERS:
        return INVALID  # prose in another script — invisible to an ASCII token count
    lowered = text.lower()
    tokens = re.findall(r"[a-z0-9_-]+", lowered)
    if len(tokens) > MAX_ANSWER_TOKENS:
        return INVALID
    if _DECLINE.match(lowered):
        return "none"  # an explicit decline IS a decision, however it is phrased
    if any(t in _NEGATION or t in _ACTING for t in tokens):
        return INVALID  # the reply argues about the routing, or performs it — neither states one
    known = {n.lower(): n for n in names}
    # `_` is normalised to `-` so `code_review` still names `code-review` rather than fragmenting.
    named = {known[t.replace("_", "-")] for t in tokens if t.replace("_", "-") in known}
    if len(named) == 1:
        return named.pop()
    if "none" in tokens and not named:
        return "none"
    return INVALID  # empty, ambiguous (several names), or naming nothing known: no decision


@dataclass(frozen=True)
class PromptRate:
    """One prompt's routing rate plus how many calls produced no answer at all (ADR 0064).

    ``rate`` is ``None`` when **every** call was :data:`INVALID` — the prompt is *unmeasured*, not
    "routed 0% of the time". Reporting 0.0 there would be a fabricated number."""

    rate: float | None
    invalid: int
    runs: int


def selection_rate(
    run_fn: Runner,
    system: str,
    prompt: str,
    names: list[str],
    runs: int,
    workdir: Path,
    *,
    target: str,
) -> PromptRate:
    """The fraction of **valid** router calls that select ``target`` for ``prompt``.

    The Tier-1 metric (ADR 0026): a smooth per-prompt rate with no 50% majority cliff, so a
    borderline prompt yields a stable rate instead of a flickering boolean.

    Calls whose reply is :data:`INVALID` (no routing decision — see :func:`parse_selection`) are
    **excluded from the denominator**, not counted as misses (ADR 0064): a call that failed to
    answer is missing data, and averaging it in as a miss silently understates recall. The count
    is returned so the caller can surface it — a rate computed from 2 of 5 calls is not the same
    evidence as one from 5 of 5, and hiding that would be a silent cap.
    """
    hits = 0
    invalid = 0
    for _ in range(runs):
        pick = parse_selection(run_fn(system, prompt, workdir), names)
        if pick == INVALID:
            invalid += 1
        elif pick == target:
            hits += 1
    valid = runs - invalid
    # A rate from ONE surviving call carried the same weight in the mean as one from five, so a
    # single stray answer could set a prompt to a flat 0.0 or 1.0 (ADR 0067). Below half the
    # samples there is not enough evidence to average — treat the prompt as unmeasured, which is
    # the loud path that already exists, rather than a confident number from thin data.
    if valid * 2 < runs:
        return PromptRate(rate=None, invalid=invalid, runs=runs)
    return PromptRate(rate=(hits / valid) if valid else None, invalid=invalid, runs=runs)


def load_triggers(plugin_dir: Path) -> list[SkillTrigger]:
    """Every skill that declares a ``tier1_trigger`` threshold, with its trigger prompts."""
    out: list[SkillTrigger] = []
    skills_dir = plugin_dir / "skills"
    if not skills_dir.is_dir():
        return out
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        evals_path = skill_dir / "evals" / "evals.json"
        if not evals_path.is_file():
            continue
        data = load_evals(evals_path)  # clean EvalsError + guaranteed dict (not a bare json crash)
        thresholds = data.get("thresholds") or {}
        if "tier1_trigger" not in thresholds:
            continue
        triggers = data.get("triggers") or {}
        md = skill_dir / "SKILL.md"
        off = md.is_file() and _is_off_listing(_frontmatter(md))
        out.append(
            SkillTrigger(
                name=str(data.get("skill_name") or skill_dir.name),
                thresholds=thresholds,
                should_trigger=list(triggers.get("should_trigger") or []),
                should_not_trigger=list(triggers.get("should_not_trigger") or []),
                off_listing=bool(off),
            )
        )
    return out


def eval_skill(
    trig: SkillTrigger,
    names: list[str],
    run_fn: Runner,
    system: str,
    runs: int,
    workdir: Path,
) -> Tier1Report:
    """Measure recall/specificity for one skill against the live listing and gate it.

    Prompts whose every call came back :data:`INVALID` are **unmeasured**: they are left out of the
    means (a fabricated 0.0 would read as a routing failure) and instead **fail the gate** with an
    explicit reason. Not measuring something is not the same as it passing, and it is not the same
    as it failing either — so the report says exactly that (ADR 0064)."""
    st = [
        selection_rate(run_fn, system, p, names, runs, workdir, target=trig.name)
        for p in trig.should_trigger
    ]
    sn = [
        selection_rate(run_fn, system, p, names, runs, workdir, target=trig.name)
        for p in trig.should_not_trigger
    ]
    st_rates = [r.rate for r in st if r.rate is not None]
    sn_rates = [r.rate for r in sn if r.rate is not None]
    unmeasured = [
        p
        for p, r in zip(
            [*trig.should_trigger, *trig.should_not_trigger], [*st, *sn], strict=True
        )
        if r.rate is None
    ]
    measured = gate.trigger_metrics(st_rates, sn_rates)
    result = gate.tier1_trigger(measured, trig.thresholds)
    reasons = list(result.reasons)
    if unmeasured:
        reasons.append(
            f"{len(unmeasured)} prompt(s) unmeasured — every router call returned no decision"
        )
    return Tier1Report(
        skill=trig.name,
        recall=measured["recall"],
        specificity=measured["specificity"],
        passed=result.passed and not unmeasured,
        reasons=reasons,
        should_trigger_rates=st_rates,
        should_not_trigger_rates=sn_rates,
        invalid_calls=sum(r.invalid for r in [*st, *sn]),
        total_calls=sum(r.runs for r in [*st, *sn]),
        unmeasured=unmeasured,
    )


def run_tier1(
    plugin_dir: Path,
    run_fn: Runner,
    *,
    skills: list[str] | None = None,
    runs: int = DEFAULT_RUNS,
    workdir: Path | None = None,
) -> list[Tier1Report]:
    """Run Tier-1 for the on-listing skills (optionally a subset) against the live listing.

    Refuses to run a mis-wired plugin (empty listing, blank description, off-listing tier1
    skill, missing trigger prompts, or an incomplete threshold) so the library guarantee does
    not depend on the caller having run ``check_wiring`` / the dry CLI first.
    """
    if runs <= 0:
        raise ValueError(f"runs must be >= 1, got {runs}")
    problems = check_wiring(plugin_dir)
    if problems:
        raise ValueError("Tier-1 wiring problems: " + "; ".join(problems))
    cards = load_listing(plugin_dir)
    names = [c.name for c in cards]
    system = build_router_system(cards)
    work = workdir or plugin_dir
    triggers = [t for t in load_triggers(plugin_dir) if skills is None or t.name in skills]
    return [eval_skill(t, names, run_fn, system, runs, work) for t in triggers]


def check_wiring(plugin_dir: Path) -> list[str]:
    """Dry-run readiness: triggers present, on-listing, and the listing is well-formed."""
    problems: list[str] = []
    cards = load_listing(plugin_dir)
    listing_names = {c.name for c in cards}
    if not cards:
        problems.append("live listing is empty (no model-invocable skills found)")
    for card in cards:
        if not card.description:
            problems.append(f"{card.name}: empty description (router can't route on it)")
    for trig in load_triggers(plugin_dir):
        if trig.off_listing:
            problems.append(
                f"{trig.name}: declares tier1_trigger but is disable-model-invocation (off-listing)"
            )
        elif trig.name not in listing_names:
            problems.append(f"{trig.name}: declares tier1_trigger but is not in the live listing")
        if not trig.should_trigger:
            problems.append(f"{trig.name}: no should_trigger prompts")
        if not trig.should_not_trigger:
            problems.append(f"{trig.name}: no should_not_trigger prompts")
        # A tier1_trigger block with no recall/specificity value would pass vacuously
        # (gate.tier1_trigger skips a None target), so a skill the router never picks could
        # merge green. Require both numeric thresholds.
        t1 = trig.thresholds.get("tier1_trigger") or {}
        if t1.get("recall") is None or t1.get("specificity") is None:
            problems.append(
                f"{trig.name}: tier1_trigger present but missing a recall/specificity threshold"
            )
    return problems
