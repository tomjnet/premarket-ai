"""The verdict policy: hard rules, the middle, the judge, review, impact."""

import pytest

from ai_api.verify import policy


def _decide(codes=(), **kwargs):
    return policy.decide(policy.Signals(codes=frozenset(codes), **kwargs))


def test_hard_rules_force_fake_and_keep_the_codes():
    found = _decide(
        {"FAKE_TICKER", "FAKE_COMPANY", "INJECTION_ATTEMPT", "NO_CORROBORATION"}
    )
    assert found.verdict == "FAKE"
    assert found.hard
    assert found.confidence == pytest.approx(0.97)
    # NO_CORROBORATION stays only with FABRICATED_CLAIM.
    assert found.reason_codes == (
        "FAKE_COMPANY",
        "FAKE_TICKER",
        "INJECTION_ATTEMPT",
    )


def test_fabricated_claim_is_fake_with_no_corroboration():
    found = _decide({"FABRICATED_CLAIM", "NO_CORROBORATION"}, source_tier="low")
    assert found.verdict == "FAKE"
    assert found.reason_codes == ("FABRICATED_CLAIM", "NO_CORROBORATION")


def test_misleading_codes():
    assert _decide({"STALE"}, source_tier="trusted").verdict == "MISLEADING"
    both = _decide({"NUMBER_MISMATCH", "SENSATIONAL_HEADLINE"})
    assert both.verdict == "MISLEADING"
    assert both.confidence == pytest.approx(0.9)
    only_style = _decide({"SENSATIONAL_HEADLINE"})
    assert only_style.confidence == pytest.approx(0.72)


def test_verified_needs_corroboration_or_a_trusted_wire():
    assert _decide(primary_source=True).confidence == pytest.approx(0.9)
    assert _decide(independent_sources=2).verdict == "VERIFIED"
    lab = _decide(source_tier="trusted")
    assert (lab.verdict, lab.confidence) == ("VERIFIED", 0.75)
    assert "lab rule" in lab.rationale
    unverified = _decide(source_tier="neutral", independent_sources=1)
    assert unverified.verdict == "UNVERIFIED"
    assert unverified.reason_codes == ("NO_CORROBORATION",)


def test_non_english_is_unverified():
    found = _decide(source_tier="trusted", english=False)
    assert found.verdict == "UNVERIFIED"
    assert found.reason_codes == ("UNSUPPORTED_LANGUAGE",)


def test_agreement_raises_the_confidence():
    rule = _decide(source_tier="trusted")
    judge = policy.JudgeView("VERIFIED", 0.9, (), "Clean [E1].")
    found = policy.combine(rule, judge)
    assert not found.disagree
    assert found.decision.confidence == pytest.approx(0.91)
    assert found.decision.rationale == "Clean [E1]."


def test_disagreement_lowers_the_confidence_and_the_rules_win():
    rule = _decide(source_tier="trusted")
    judge = policy.JudgeView("UNVERIFIED", 0.9, ("NO_CORROBORATION",), "x")
    found = policy.combine(rule, judge)
    assert found.disagree
    assert found.decision.verdict == "VERIFIED"
    assert found.decision.confidence < 0.7
    assert "NO_CORROBORATION" not in found.decision.reason_codes


def test_the_judge_decides_the_uncertain_middle():
    rule = _decide(source_tier="neutral")
    judge = policy.JudgeView("MISLEADING", 0.95, ("SENSATIONAL_HEADLINE",))
    found = policy.combine(rule, judge)
    assert found.disagree
    assert found.decision.verdict == "MISLEADING"
    assert found.decision.reason_codes == ("SENSATIONAL_HEADLINE",)


def test_the_judge_never_overrides_a_hard_rule():
    rule = _decide({"FAKE_TICKER"})
    judge = policy.JudgeView("VERIFIED", 1.0)
    assert policy.combine(rule, judge).decision.verdict == "FAKE"


def test_review_reasons():
    low = policy.combine(_decide(source_tier="low"), None)
    assert policy.review_reasons(low, 0.7) == ["low_confidence"]
    disagree = policy.combine(
        _decide(source_tier="trusted"), policy.JudgeView("MISLEADING", 0.99)
    )
    assert policy.review_reasons(disagree, 0.7) == [
        "low_confidence",
        "judge_disagrees",
    ]
    fake = policy.combine(_decide({"FAKE_TICKER"}), None)
    assert policy.review_reasons(fake, 0.7) == []
    assert policy.review_reasons(fake, 0.7, guard_unsafe=True) == [
        "guard_unsafe"
    ]


def test_impact_is_relevance_times_company_size():
    top = policy.impact("Apple reports Q3 revenue of $85B", 0, 50)
    assert (top.relevance, top.score, top.level) == (1.0, 1.0, "high")
    small = policy.impact("Visa raises quarterly dividend", 49, 50)
    assert small.score == pytest.approx(0.3)
    assert small.level == "low"
    outside = policy.impact("Quantavex names a CFO", None, 50)
    assert outside.score == pytest.approx(0.24)
