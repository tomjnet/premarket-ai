"""The verdict policy: hard rules first, then the LLM judge in the middle.

``decide`` turns the checks' findings into a rule-based verdict:

- **FAKE** (hard): FAKE_COMPANY, FAKE_TICKER, SPOOFED_SOURCE,
  CONTRADICTED_BY_FILING or FABRICATED_CLAIM. The judge is not asked and
  can't override it.
- **MISLEADING**: NUMBER_MISMATCH, STALE or SENSATIONAL_HEADLINE on a real
  company's story.
- **VERIFIED**: a primary source (an 8-K or its press release) or two
  independent trusted outlets report it. Lab rule: vendor-sim's stories
  exist nowhere else, so one trusted-tier newswire with every check clean
  also counts (with a lower confidence).
- **UNVERIFIED**: nothing contradicts it, but nothing corroborates it
  (NO_CORROBORATION); also every non-English item.

``combine`` then weighs the rule verdict (0.6) against the judge's (0.4):
agreement raises the confidence, disagreement lowers it and always sends
the item to review. The judge decides only the uncertain middle
(VERIFIED, UNVERIFIED, MISLEADING).
"""

from __future__ import annotations

import dataclasses
import re

from ai_api.verify import evidence as ev

VERIFIED = "VERIFIED"
UNVERIFIED = "UNVERIFIED"
MISLEADING = "MISLEADING"
FAKE = "FAKE"
VERDICTS = (VERIFIED, UNVERIFIED, MISLEADING, FAKE)
JUDGE_VERDICTS = (VERIFIED, UNVERIFIED, MISLEADING)

HARD_FAKE_CODES = frozenset(
    {
        "FAKE_COMPANY",
        "FAKE_TICKER",
        "SPOOFED_SOURCE",
        ev.CONTRADICTED_BY_FILING,
        ev.FABRICATED_CLAIM,
    }
)
# Codes that make a real company's story MISLEADING, with the rule-based
# confidence each one gives.
MISLEADING_CODES = {
    ev.NUMBER_MISMATCH: 0.85,
    "STALE": 0.85,
    ev.SENSATIONAL_HEADLINE: 0.72,
}
# Codes the judge may add (never a hard code).
JUDGE_CODES = frozenset(
    {
        ev.NUMBER_MISMATCH,
        ev.SENSATIONAL_HEADLINE,
        "STALE",
        ev.NO_CORROBORATION,
        ev.CONFLICTING_VERSION,
    }
)
_RULE_WEIGHT = 0.6
_JUDGE_WEIGHT = 0.4
_AGREEMENT_BONUS = 0.1
_MAX_CONFIDENCE = 0.99

# Review reasons (ai.review_task.reasons).
LOW_CONFIDENCE = "low_confidence"
JUDGE_DISAGREES = "judge_disagrees"
GUARD_UNSAFE = "guard_unsafe"
UNSUPPORTED_LANGUAGE = "unsupported_language"


@dataclasses.dataclass(frozen=True)
class Signals:
    """What the checks found, as the policy needs it.

    Attributes:
        codes: Every reason code of the rules, the AI run and the checks.
        source_tier: ``trusted``, ``neutral``, ``low``, ``blocked`` or
            ``unknown`` (not in the reputation table).
        primary_source: An SEC filing or press release reports the story.
        independent_sources: Other trusted outlets that report it.
        english: False skips the model steps (UNSUPPORTED_LANGUAGE).
    """

    codes: frozenset[str]
    source_tier: str = "unknown"
    primary_source: bool = False
    independent_sources: int = 0
    english: bool = True


@dataclasses.dataclass(frozen=True)
class Decision:
    """A verdict with its confidence, codes and a one-line reason.

    Attributes:
        verdict: VERIFIED, UNVERIFIED, MISLEADING or FAKE.
        confidence: 0 to 1.
        reason_codes: In display order.
        rationale: Why, in one or two sentences.
        hard: A hard rule decided it (the judge isn't asked).
    """

    verdict: str
    confidence: float
    reason_codes: tuple[str, ...]
    rationale: str
    hard: bool = False


@dataclasses.dataclass(frozen=True)
class JudgeView:
    """The judge's answer, as the policy needs it.

    Attributes:
        verdict: VERIFIED, UNVERIFIED or MISLEADING.
        confidence: 0 to 1.
        reason_codes: Codes it found (filtered to ``JUDGE_CODES``).
        rationale: Its explanation, citing evidence ids.
    """

    verdict: str
    confidence: float
    reason_codes: tuple[str, ...] = ()
    rationale: str = ""


@dataclasses.dataclass(frozen=True)
class Combined:
    """The final verdict of the AI.

    Attributes:
        decision: Verdict, confidence, codes and rationale.
        disagree: The judge and the rules disagree (always reviewed).
    """

    decision: Decision
    disagree: bool = False


def _passthrough(codes: frozenset[str]) -> set[str]:
    """Codes that inform but never decide (injection, conflicting)."""
    return codes & {"INJECTION_ATTEMPT", ev.CONFLICTING_VERSION}


def decide(signals: Signals) -> Decision:
    """The rule-based verdict (see the module docstring).

    Args:
        signals: What the checks found.

    Returns:
        The verdict, its confidence and codes.
    """
    codes = signals.codes
    hard = codes & HARD_FAKE_CODES
    if hard:
        kept = set(codes) - {"UNSUPPORTED_LANGUAGE"}
        if ev.FABRICATED_CLAIM not in hard:
            kept.discard(ev.NO_CORROBORATION)
        confidence = min(_MAX_CONFIDENCE, 0.95 + 0.02 * (len(hard) - 1))
        return Decision(
            FAKE,
            confidence,
            tuple(ev.ordered(kept)),
            f"Hard rule: {', '.join(ev.ordered(hard))}. Deterministic "
            "evidence decides FAKE; the LLM judge can't override it.",
            hard=True,
        )
    extra = _passthrough(codes)
    if not signals.english:
        return Decision(
            UNVERIFIED,
            0.5,
            tuple(ev.ordered({"UNSUPPORTED_LANGUAGE", *extra})),
            "Not English: the model steps were skipped and an analyst "
            "has to read it.",
        )
    misleading = {
        c: MISLEADING_CODES[c] for c in codes if c in MISLEADING_CODES
    }
    if misleading:
        confidence = max(misleading.values())
        if len(misleading) > 1:
            confidence = min(_MAX_CONFIDENCE, confidence + 0.05)
        return Decision(
            MISLEADING,
            confidence,
            tuple(ev.ordered({*misleading, *extra})),
            f"A real company's story with wrong key facts: "
            f"{', '.join(ev.ordered(set(misleading)))}.",
        )
    if signals.primary_source or signals.independent_sources >= 2:
        how = (
            "a primary source (SEC filing)"
            if signals.primary_source
            else f"{signals.independent_sources} independent trusted outlets"
        )
        return Decision(
            VERIFIED,
            0.9,
            tuple(ev.ordered(extra)),
            f"Confirmed by {how}; no check contradicts it.",
        )
    if signals.source_tier == "trusted":
        confidence = 0.75 + 0.05 * min(signals.independent_sources, 1)
        return Decision(
            VERIFIED,
            confidence,
            tuple(ev.ordered(extra)),
            "From a trusted-tier newswire with every check clean (lab rule: "
            "the synthetic story can't be found anywhere else).",
        )
    return Decision(
        UNVERIFIED,
        0.6,
        tuple(ev.ordered({ev.NO_CORROBORATION, *extra})),
        "Nothing contradicts it, but no primary source or trusted outlet "
        "reports it yet.",
    )


def _codes_for(verdict: str, codes: set[str]) -> set[str]:
    """Drops codes that don't fit the final verdict."""
    if verdict == VERIFIED:
        return codes - set(MISLEADING_CODES) - {ev.NO_CORROBORATION}
    if verdict == UNVERIFIED:
        return codes - set(MISLEADING_CODES)
    return codes - {ev.NO_CORROBORATION}


def combine(rule: Decision, judge: JudgeView | None) -> Combined:
    """The final verdict from the rules and the judge.

    Args:
        rule: The rule-based decision.
        judge: The judge's answer; None when it wasn't asked (a hard rule,
            a non-English item) or failed.

    Returns:
        The final decision, and whether the two disagreed.
    """
    if rule.hard or judge is None:
        return Combined(rule)
    judge_codes = set(judge.reason_codes) & JUDGE_CODES
    rule_score = _RULE_WEIGHT * rule.confidence
    judge_score = _JUDGE_WEIGHT * judge.confidence
    if judge.verdict == rule.verdict:
        confidence = min(
            _MAX_CONFIDENCE, rule_score + judge_score + _AGREEMENT_BONUS
        )
        codes = _codes_for(rule.verdict, set(rule.reason_codes) | judge_codes)
        decision = Decision(
            rule.verdict,
            round(confidence, 3),
            tuple(ev.ordered(codes)),
            judge.rationale or rule.rationale,
        )
        return Combined(decision)
    if rule_score >= judge_score:
        verdict = rule.verdict
        rationale = rule.rationale
        codes = set(rule.reason_codes)
    else:
        verdict = judge.verdict
        rationale = judge.rationale or rule.rationale
        codes = set(rule.reason_codes) | judge_codes
    # Between 0.35 and 0.7: always below the review threshold's default.
    confidence = 0.7 * max(rule_score, judge_score) / (rule_score + judge_score)
    decision = Decision(
        verdict,
        round(confidence, 3),
        tuple(ev.ordered(_codes_for(verdict, codes))),
        rationale,
    )
    return Combined(decision, disagree=True)


def review_reasons(
    final: Combined,
    min_confidence: float,
    *,
    guard_unsafe: bool = False,
    english: bool = True,
) -> list[str]:
    """Why an item goes to the human review queue (empty: it doesn't).

    Args:
        final: The combined decision.
        min_confidence: HITL_CONFIDENCE_MIN (0.70).
        guard_unsafe: Llama Guard flagged the item.
        english: False for an item in another language.

    Returns:
        The reasons, in a fixed order.
    """
    reasons = []
    if final.decision.confidence < min_confidence:
        reasons.append(LOW_CONFIDENCE)
    if final.disagree:
        reasons.append(JUDGE_DISAGREES)
    if guard_unsafe:
        reasons.append(GUARD_UNSAFE)
    if not english:
        reasons.append(UNSUPPORTED_LANGUAGE)
    return reasons


# --- market impact ------------------------------------------------------------

_HIGH_RELEVANCE = re.compile(
    r"\b(revenue|earnings|eps|profit|loss|guidance|outlook|forecast|"
    r"acquir\w*|merger|takeover|resign\w*|ceo|breakup|split|spin-?off|"
    r"halt\w*|bankruptcy|fda|probe|inquiry|investigation)\b",
    re.IGNORECASE,
)
_MEDIUM_RELEVANCE = re.compile(
    r"\b(dividend|buyback|repurchase|partnership|contract|deal|cfo|"
    r"chief financial officer|appoint\w*|names)\b",
    re.IGNORECASE,
)
_SMALLEST_WEIGHT = 0.5
_OUTSIDE_UNIVERSE_WEIGHT = 0.4


@dataclasses.dataclass(frozen=True)
class Impact:
    """How much an item could move the market.

    Attributes:
        relevance: 1.0 (earnings, deals, executives leaving...), 0.6
            (dividends, buybacks, partnerships) or 0.3.
        score: relevance x company size, 0 to 1 (the review order).
        level: ``high`` (>= 0.66), ``medium`` (>= 0.33) or ``low``.
    """

    relevance: float
    score: float
    level: str


def impact(headline: str, rank: int | None, universe_size: int) -> Impact:
    """Relevance of the news kind times the company's size.

    Args:
        headline: The headline.
        rank: The company's market-cap rank in the lab universe (0 is the
            largest), or None for a company outside it.
        universe_size: How many companies the universe has.

    Returns:
        The relevance, the score and its level.
    """
    if _HIGH_RELEVANCE.search(headline):
        relevance = 1.0
    elif _MEDIUM_RELEVANCE.search(headline):
        relevance = 0.6
    else:
        relevance = 0.3
    if rank is None:
        size = _OUTSIDE_UNIVERSE_WEIGHT
    else:
        span = max(universe_size - 1, 1)
        size = 1.0 - (1.0 - _SMALLEST_WEIGHT) * min(rank, span) / span
    score = round(relevance * size, 3)
    if score >= 0.66:
        level = "high"
    elif score >= 0.33:
        level = "medium"
    else:
        level = "low"
    return Impact(relevance, score, level)
