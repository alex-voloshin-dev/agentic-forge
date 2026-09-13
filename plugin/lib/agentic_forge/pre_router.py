"""Deterministic pre-router: name the matching skill IN the prompt's context (ADR 0089).

The measured problem (ADR 0088): a live session reaches for the right skill on ~0.35 of the
requests squarely in its domain, and the SessionStart note lifted that to 0.56 — leaving nearly
half, concentrated on the skills with an obvious do-it-by-hand path. A standing note is advice the
model weighs once per session; a line attached to *this* prompt is a suggestion it reads at the
moment of deciding. This module makes that line, without a model call, on every prompt.

It is a classifier over the plugin's own eval data: each skill's ``should_trigger`` prompts are the
positive examples, its ``should_not_trigger`` prompts the negatives, its description a weaker
positive. A prompt is scored against every example by IDF-weighted cosine over word unigrams and
bigrams, and a skill is suggested only when it wins **clearly** — above an absolute floor, ahead of
the runner-up by a margin, and not beaten by one of its own negatives. Ambiguity abstains: a wrong
nudge costs more than no nudge, and a hook that fires on everything is ignored on everything.

Pure and deterministic (``build_index`` / ``suggest`` / ``self_check``), fully tested; the hook in
``hooks/scripts/pre_router.py`` is a thin I/O wrapper. Runs on the oldest ``python3`` the hooks are
contracted for (3.9) — no model, no third-party imports.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from agentic_forge.frontmatter import parse as parse_frontmatter

__all__ = [
    "Index",
    "Suggestion",
    "SelfCheck",
    "MIN_SCORE",
    "MARGIN",
    "NEG_VETO",
    "features",
    "build_index",
    "suggest",
    "render_context",
    "self_check",
]

# Decision thresholds. MIN_SCORE is the floor the winning similarity must clear; MARGIN is how far
# ahead of the runner-up it must be. Both err toward abstaining: precision over recall, because the
# hook's downside is a wrong nudge on every prompt, and its upside is realised by Tier-1b (ADR 0088)
# only if the nudges it does make are right. Calibrated on the leave-one-out self-check.
# Calibrated on the leave-one-out self-check over the plugin's 84 trigger + 71 anti-trigger prompts
# (ADR 0089): at 0.40 / 0.15 — recall 0.500, precision 0.955, wrong-skill 0, false-suggest 2. The
# band 0.30-0.50 never routes to a WRONG skill above MARGIN 0.10; this point trades the last of
# recall for the last of precision, because a wrong nudge on every prompt is the failure mode.
MIN_SCORE = 0.40  # the profile must explain this share of the prompt's weighted meaning
MARGIN = 0.15  # …and lead the runner-up skill by this much
NEG_VETO = 0.50  # the skill's negative-only vocabulary explaining this much of the prompt vetoes

_STOP = frozenset(
    "a an the and or of to for in on at by with from into as is are be this that these those it "
    "its my our your their we you i me us them do does did done can could should would will "
    "please just some any all about over under up out not no so if then than also very get "
    "make".split()
)
_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.-]*")


def _stem(token: str) -> str:
    """A crude English stem: enough to make `reviewing`, `reviews` and `review` one feature
    without a dependency. Deliberately conservative — short words are left alone."""
    for suffix in ("ing", "ies", "ed", "es", "s"):
        if len(token) > 4 and token.endswith(suffix):
            stem = token[: -len(suffix)]
            return stem + "y" if suffix == "ies" else stem
    return token


def features(text: str) -> set[str]:
    """Word unigrams + adjacent bigrams of ``text`` after lowercasing, stop-word removal and
    stemming. Bigrams carry the phrases that separate neighbours (`test strategy` vs `work
    plan`)."""
    words = [_stem(w) for w in _TOKEN.findall(text.lower()) if w not in _STOP]
    words = [w for w in words if w]
    out = set(words)
    # no `strict=`: the hook runs on 3.9 (ADR 0050); the shorter list bounds it anyway
    out.update(f"{a} {b}" for a, b in zip(words, words[1:]))  # noqa: B905
    return out


@dataclass(frozen=True)
class _Doc:
    skill: str
    kind: str  # "pos" | "neg"
    text: str
    feats: frozenset[str]


@dataclass
class Index:
    """The pre-router's whole state.

    Per skill: a **profile** (its description's features ∪ its should_trigger prompts'), the raw
    positive and negative example docs, and IDF weights computed **across skill profiles** — one
    document per skill — so a feature is discounted for appearing in many *skills*, not many
    examples. `feature` and `review` appear in most profiles and weigh little; `changelog`,
    `incident`, `wcag` appear in one and weigh a lot. That is the axis the decision is made on.
    """

    skills: list[str]
    descriptions: dict[str, frozenset[str]]
    positives: dict[str, list[_Doc]]
    negatives: dict[str, list[_Doc]]
    idf: dict[str, float]
    namespace: str = "agentic-forge"
    unknown_weight: float = 0.0

    def _own_trigger_feats(self, skill: str, *, exclude: _Doc | None = None) -> set[str]:
        feats: set[str] = set()
        for doc in self.positives.get(skill, []):
            if doc is not exclude:
                feats |= doc.feats
        return feats

    def profile(self, skill: str, *, exclude: _Doc | None = None) -> frozenset[str]:
        """The skill's vocabulary: its trigger prompts, plus its description MINUS any word that
        belongs to another skill's trigger prompts and not to its own.

        That subtraction is the whole trick. This plugin's descriptions are contrastive on purpose —
        "Not for the technical design (architecture)", "For a quick lint use code-review instead" —
        which is exactly what makes the *model* route well and exactly what poisons a bag of words:
        it puts `prd` into `architecture`'s profile and `implement` into `security-review`'s. Words
        the skill's own triggers use are kept whatever the neighbours say."""
        own = self._own_trigger_feats(skill, exclude=exclude)
        foreign: set[str] = set()
        for other in self.skills:
            if other != skill:
                foreign |= self._own_trigger_feats(other)
        desc = set(self.descriptions.get(skill, frozenset())) - (foreign - own)
        return frozenset(own | desc)

    def negative_only(self, skill: str, *, exclude: _Doc | None = None) -> frozenset[str]:
        """Features that appear in the skill's should_not_trigger prompts and NOT in its profile —
        the vocabulary of what the skill is explicitly not for (`fix`, `failing`, `explain`)."""
        neg: set[str] = set()
        for doc in self.negatives.get(skill, []):
            if doc is not exclude:
                neg |= doc.feats
        return frozenset(neg - self.profile(skill, exclude=exclude))

    def weight(self, feats: frozenset[str]) -> float:
        """IDF-weighted mass. A feature NO skill's profile contains gets the maximum weight: a
        word none of the skills use is the strongest evidence the prompt is about something else,
        and dropping it from the denominator let `Run the app and screenshot it` score 0.60 on
        the single word `app`."""
        return sum(self.idf.get(f, self.unknown_weight) for f in feats)

    def coverage(self, prompt_feats: frozenset[str], by: frozenset[str]) -> float:
        """The share of the prompt's IDF-weighted meaning that ``by`` explains, in [0, 1].
        Asymmetric on purpose: a long description is not penalised for being long, and a short
        prompt is scored on how much of *it* the skill accounts for."""
        total = self.weight(prompt_feats)
        return self.weight(prompt_feats & by) / total if total else 0.0


def _load_skill_examples(
    plugin_dir: Path,
) -> tuple[list[str], dict[str, frozenset[str]], dict[str, list[_Doc]], dict[str, list[_Doc]]]:
    """Every on-listing skill's description features and trigger prompts as example documents."""
    skills: list[str] = []
    descriptions: dict[str, frozenset[str]] = {}
    positives: dict[str, list[_Doc]] = {}
    negatives: dict[str, list[_Doc]] = {}
    skills_dir = plugin_dir / "skills"
    if not skills_dir.is_dir():
        return skills, descriptions, positives, negatives
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        md = skill_dir / "SKILL.md"
        evals_path = skill_dir / "evals" / "evals.json"
        if not md.is_file() or not evals_path.is_file():
            continue
        try:
            fm, _ = parse_frontmatter(md.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — a malformed SKILL.md is Tier-0's problem, not the hook's
            continue
        if fm.get("disable-model-invocation") is True:
            continue  # off-listing: the model cannot invoke it, so never suggest it
        try:
            data = json.loads(evals_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        triggers = data.get("triggers") or {}
        pos = [str(p) for p in triggers.get("should_trigger") or []]
        neg = [str(p) for p in triggers.get("should_not_trigger") or []]
        if not pos:
            continue
        name = str(fm.get("name") or skill_dir.name)
        skills.append(name)
        descriptions[name] = frozenset(features(str(fm.get("description") or "")))
        positives[name] = [_Doc(name, "pos", x, frozenset(features(x))) for x in pos]
        negatives[name] = [_Doc(name, "neg", x, frozenset(features(x))) for x in neg]
    return skills, descriptions, positives, negatives


def _idf_over_profiles(profiles: dict[str, frozenset[str]]) -> dict[str, float]:
    df: dict[str, int] = {}
    for feats in profiles.values():
        for f in feats:
            df[f] = df.get(f, 0) + 1
    n = max(len(profiles), 1)
    return {f: math.log(1.0 + n / c) for f, c in df.items()}


def _plugin_namespace(plugin_dir: Path) -> str:
    """The prefix a live session shows plugin skills under — the plugin's manifest name."""
    try:
        manifest = json.loads((plugin_dir / ".claude-plugin" / "plugin.json").read_text("utf-8"))
        return str(manifest.get("name") or "agentic-forge")
    except (OSError, json.JSONDecodeError, TypeError):
        return "agentic-forge"


def build_index(plugin_dir: Path | str) -> Index:
    """Index every on-listing skill's description and eval triggers (cheap: a few ms)."""
    plugin_dir = Path(plugin_dir)
    skills, descriptions, positives, negatives = _load_skill_examples(plugin_dir)
    index = Index(
        skills=skills,
        descriptions=descriptions,
        positives=positives,
        negatives=negatives,
        idf={},
        namespace=_plugin_namespace(plugin_dir),
    )
    index.idf = _idf_over_profiles({s: index.profile(s) for s in skills})
    index.unknown_weight = max(index.idf.values(), default=0.0)
    return index


@dataclass(frozen=True)
class Suggestion:
    skill: str
    score: float
    runner_up: str | None
    runner_up_score: float
    matched: str  # the words that carried the decision — the evidence


def suggest(prompt: str, index: Index, *, _exclude: _Doc | None = None) -> Suggestion | None:
    """The one skill this prompt clearly matches, or None.

    Wins require all three: the skill's profile covers at least :data:`MIN_SCORE` of the prompt's
    weighted meaning; the skill's *negative-only* vocabulary does not cover :data:`NEG_VETO` of it
    (the prompt reads like what the skill is explicitly not for); and the skill leads the runner-up
    by :data:`MARGIN`. Anything less abstains."""
    feats = frozenset(features(prompt))
    if not feats:
        return None
    scored: list[tuple[float, str, frozenset[str]]] = []
    for skill in index.skills:
        prof = index.profile(skill, exclude=_exclude)
        score = index.coverage(feats, prof)
        if score <= 0.0:
            continue
        if index.coverage(feats, index.negative_only(skill, exclude=_exclude)) >= NEG_VETO:
            continue  # its own negatives say no
        scored.append((score, skill, feats & prof))
    if not scored:
        return None
    scored.sort(key=lambda x: (-x[0], x[1]))
    top_score, top_skill, hit = scored[0]
    runner = scored[1] if len(scored) > 1 else None
    runner_score = runner[0] if runner else 0.0
    if top_score < MIN_SCORE or top_score - runner_score < MARGIN:
        return None
    evidence = " ".join(sorted(hit, key=lambda f: -index.idf.get(f, 0.0))[:4])
    return Suggestion(
        skill=top_skill,
        score=top_score,
        runner_up=runner[1] if runner else None,
        runner_up_score=runner_score,
        matched=evidence,
    )


def render_context(s: Suggestion, namespace: str) -> str:
    """The line the hook injects. Says which skill, why it was matched, and what to do — and that
    it is a suggestion, so a genuinely different request is not railroaded into it."""
    return (
        f"agentic-forge pre-router: this request reads like the `{namespace}:{s.skill}` skill "
        f"(matched on: {s.matched}). If that is what is being asked, invoke "
        f"`{namespace}:{s.skill}` with the Skill tool rather than doing the work directly — it "
        f"is a workflow with its own gates and handoff, not reference material. If the request "
        f"is really something else, ignore this."
    )


@dataclass
class SelfCheck:
    """Leave-one-out estimate of the pre-router on the plugin's own trigger data (ADR 0089)."""

    hits: int = 0  # should_trigger prompt suggested its own skill
    misses: int = 0  # …suggested nothing
    wrong: int = 0  # …suggested a DIFFERENT skill — the costly error
    false_suggest: int = 0  # should_not_trigger prompt suggested the skill it must not
    negatives: int = 0
    per_skill: dict[str, dict[str, int]] = field(default_factory=dict)
    wrong_examples: list[tuple[str, str, str]] = field(default_factory=list)  # (prompt, want, got)

    @property
    def positives(self) -> int:
        return self.hits + self.misses + self.wrong

    @property
    def recall(self) -> float:
        return self.hits / self.positives if self.positives else 0.0

    @property
    def precision(self) -> float:
        made = self.hits + self.wrong + self.false_suggest
        return self.hits / made if made else 1.0

    def summary(self) -> str:
        return (
            f"pre-router self-check: recall={self.recall:.3f} ({self.hits}/{self.positives}), "
            f"precision={self.precision:.3f}, wrong-skill={self.wrong}, "
            f"false-suggest={self.false_suggest}/{self.negatives}"
        )


def self_check(index: Index) -> SelfCheck:
    """Classify every example with itself removed from the index — the honest estimate, since the
    examples are also the training set. ``wrong`` (a should-trigger prompt routed to another skill)
    is the error the thresholds are tuned to keep near zero; a miss just means no nudge."""
    out = SelfCheck()
    docs = [d for s in index.skills for d in (*index.positives[s], *index.negatives[s])]
    for doc in docs:
        got = suggest(doc.text, index, _exclude=doc)
        slot = out.per_skill.setdefault(doc.skill, {"hit": 0, "miss": 0, "wrong": 0, "false": 0})
        if doc.kind == "pos":
            if got is None:
                out.misses += 1
                slot["miss"] += 1
            elif got.skill == doc.skill:
                out.hits += 1
                slot["hit"] += 1
            else:
                out.wrong += 1
                slot["wrong"] += 1
                out.wrong_examples.append((doc.text, doc.skill, got.skill))
        else:
            out.negatives += 1
            if got is not None and got.skill == doc.skill:
                out.false_suggest += 1
                slot["false"] += 1
    return out
