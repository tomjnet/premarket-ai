"""The judge's checks, Llama Guard's parser and the cloud budget."""

import asyncio
import types

import fakeredis
import pytest

from ai_api.guard import llama_guard
from ai_api.guard import sanitize
from ai_api.llm import budget
from ai_api.verify import evidence as ev
from ai_api.verify import judge as judge_lib
from ai_api.verify import models


class ScriptedModel:
    """A chat model whose structured answers are queued (cost per call)."""

    def __init__(self, answers, cost=0.0):
        """Queues ``answers`` (Judgement or Exception)."""
        self.answers = list(answers)
        self.cost = cost
        self.prompts = []

    def with_structured_output(self, schema, **kwargs):
        """Returns itself; the schema is always Judgement here."""
        del schema, kwargs
        return self

    async def ainvoke(self, messages, config=None):
        """Records the prompt and returns the next answer."""
        del config
        self.prompts.append(messages)
        answer = self.answers.pop(0)
        raw = types.SimpleNamespace(
            response_metadata={
                "headers": {"x-litellm-response-cost": str(self.cost)}
            }
        )
        if isinstance(answer, Exception):
            return {"raw": raw, "parsed": None, "parsing_error": answer}
        return {"raw": raw, "parsed": answer, "parsing_error": None}


def _answer(**overrides):
    values = {
        "verdict": "VERIFIED",
        "confidence": 0.9,
        "reason_codes": [],
        "evidence_ids": ["E1"],
        "rationale": "Trusted wire, clean checks [E1].",
    }
    values.update(overrides)
    return models.Judgement(**values)


_EVIDENCE = [
    ("E1", ev.Evidence("source", None, "wire: trusted source")),
    ("E2", ev.Evidence("style", None, "sober headline")),
]
_ITEM = sanitize.Sanitized("Apple raises dividend", "Apple said so.")


def _judge(local, cloud=None, spend=None):
    return judge_lib.Judge(
        local,
        "main-gpu4gb",
        cloud=cloud,
        cloud_name="cloud-openai",
        budget=spend,
    )


def test_a_clean_answer_is_kept():
    model = ScriptedModel([_answer()])
    found = asyncio.run(_judge(model).judge(_ITEM, "VND-1", _EVIDENCE, {}))
    assert found.view.verdict == "VERIFIED"
    assert found.evidence_ids == ("E1",)
    assert found.model == "main-gpu4gb"
    system, user = model.prompts[0]
    assert "FAKE is not one of your choices" in system[1]
    assert '<source n="E2">' in user[1]


def test_unknown_evidence_ids_are_retried_then_fail():
    bad = _answer(evidence_ids=["E9"], rationale="See [E9].")
    model = ScriptedModel([bad, bad])
    with pytest.raises(judge_lib.JudgeError):
        asyncio.run(_judge(model).judge(_ITEM, "VND-1", _EVIDENCE, {}))
    assert "cited no evidence id" in model.prompts[1][0][1]


def test_citations_in_the_rationale_count_and_bad_ones_are_removed():
    answer = _answer(evidence_ids=[], rationale="Clean [E2] and [E7].")
    found = asyncio.run(
        _judge(ScriptedModel([answer])).judge(_ITEM, "VND-1", _EVIDENCE, {})
    )
    assert found.evidence_ids == ("E2",)
    assert found.view.rationale == "Clean [E2] and ."


def test_advice_in_the_rationale_is_dropped():
    answer = _answer(rationale="Investors should buy the stock now [E1].")
    found = asyncio.run(
        _judge(ScriptedModel([answer])).judge(_ITEM, "VND-1", _EVIDENCE, {})
    )
    assert found.view.rationale == ""


def test_a_parse_failure_is_retried_once():
    model = ScriptedModel([ValueError("bad json"), _answer()])
    found = asyncio.run(_judge(model).judge(_ITEM, "VND-1", _EVIDENCE, {}))
    assert found.view.verdict == "VERIFIED"


def test_escalation_counts_the_cost_and_stops_at_the_cap():
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    spend = budget.CloudBudget(redis, 0.01)
    cloud = ScriptedModel([_answer(confidence=0.8)] * 3, cost=0.004)
    judge = _judge(ScriptedModel([]), cloud=cloud, spend=spend)

    async def run():
        results = []
        while await judge.can_escalate():
            results.append(
                await judge.judge(_ITEM, "VND-1", _EVIDENCE, {}, cloud=True)
            )
        return results, await spend.spent()

    results, spent = asyncio.run(run())
    assert len(results) == 3
    assert all(r.escalated and r.model == "cloud-openai" for r in results)
    assert spent == pytest.approx(0.012)


def test_no_cloud_means_no_escalation():
    judge = _judge(ScriptedModel([]))
    assert not asyncio.run(judge.can_escalate())
    assert judge.in_band(0.55)
    assert not judge.in_band(0.7)


def test_llama_guard_answers():
    assert llama_guard.parse("safe").safe
    unsafe = llama_guard.parse("unsafe\nS5,S10")
    assert not unsafe.safe
    assert unsafe.categories == ("S5", "S10")
    assert "defamation" in unsafe.describe()
    # Anything that isn't clearly "safe" is unsafe.
    assert not llama_guard.parse("I cannot comply").safe
    assert llama_guard.Verdict.from_json(None).describe().startswith("not run")
    # Advice alone doesn't block a chat question (the app refuses advice).
    assert not llama_guard.parse("unsafe\nS6").blocks_question()
    assert llama_guard.parse("unsafe\nS6,S1").blocks_question()
    assert not llama_guard.Verdict(ran=False).blocks_question()


def test_llama_guard_fails_open_when_unreachable():
    class Down:
        async def ainvoke(self, messages):
            raise ConnectionError("gateway down")

    found = asyncio.run(llama_guard.Guard(Down()).check_news("h", "b"))
    assert found == llama_guard.Verdict(ran=False)
