"""The LLM judge: the main local model, or the cloud model when escalated.

The judge reads the sanitized item and the numbered evidence and answers a
``models.Judgement``. Its answer is checked before it is used:

- it must cite at least one evidence id that exists (unknown ids and their
  bracket citations are removed; a second answer without a valid id means
  the judge failed, and the rules decide alone);
- its rationale must not give investment advice (it is dropped if it
  does);
- its codes are limited to the ones a judge may add.

Escalation (``LLM cost`` in the plan): when the combined confidence falls
in the uncertain band (0.50 to 0.70), the item is judged again by the
cloud model (``cloud-openai`` by default), but only while the month's
cloud spend is under the cap. The cost comes back from the gateway.
"""

from __future__ import annotations

from collections.abc import Sequence
import dataclasses
import logging
import re
from typing import Any

from langchain_core import language_models
from langchain_core import runnables
import pydantic

from ai_api.guard import output
from ai_api.guard import sanitize
from ai_api.llm import budget as budget_lib
from ai_api.verify import evidence as ev
from ai_api.verify import models
from ai_api.verify import policy
from ai_api.verify import prompts

_log = logging.getLogger(__name__)
_CITATION = re.compile(r"\[(E\d{1,3})\]")
_MAX_RATIONALE_CHARS = 400
_COST_HEADER = "x-litellm-response-cost"
_CITE_REMINDER = (
    "Your previous answer cited no evidence id that exists. Cite the ids "
    "(E1, E2, ...) of the evidence you used."
)


class JudgeError(RuntimeError):
    """The judge's answer didn't parse or cited no evidence."""


@dataclasses.dataclass(frozen=True)
class JudgeResult:
    """A checked answer of the judge.

    Attributes:
        view: The verdict, confidence, codes and rationale.
        model: The gateway alias that answered.
        evidence_ids: The valid evidence ids it cited.
        cost_usd: The call's cost (cloud only; 0 for local models).
        escalated: The cloud model answered.
    """

    view: policy.JudgeView
    model: str
    evidence_ids: tuple[str, ...]
    cost_usd: float = 0.0
    escalated: bool = False


def _cost(raw: Any) -> float:
    metadata = getattr(raw, "response_metadata", None) or {}
    headers = metadata.get("headers") or {}
    try:
        return float(headers.get(_COST_HEADER, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def clean_rationale(text: str, valid: set[str]) -> str:
    """One line, citations of missing evidence removed, no advice.

    Args:
        text: The judge's rationale.
        valid: The evidence ids that exist.

    Returns:
        The cleaned rationale ("" when it gave investment advice).
    """
    text = _CITATION.sub(
        lambda m: m.group() if m.group(1) in valid else "", text
    )
    text = " ".join(text.split())
    if output.investment_advice(text):
        return ""
    if len(text) > _MAX_RATIONALE_CHARS:
        text = text[: _MAX_RATIONALE_CHARS - 1].rstrip() + "…"
    return text


def check(answer: models.Judgement, valid: set[str]) -> JudgeResult | None:
    """Checks one answer; None when it cites no valid evidence id.

    Args:
        answer: The parsed answer.
        valid: The evidence ids that exist.

    Returns:
        The checked result (model and cost filled in by the caller).
    """
    cited = tuple(dict.fromkeys(i for i in answer.evidence_ids if i in valid))
    cited += tuple(
        i
        for i in dict.fromkeys(_CITATION.findall(answer.rationale))
        if i in valid and i not in cited
    )
    if not cited:
        return None
    view = policy.JudgeView(
        verdict=answer.verdict,
        confidence=round(float(answer.confidence), 3),
        reason_codes=tuple(
            c
            for c in ev.ordered(set(answer.reason_codes))
            if c in policy.JUDGE_CODES
        ),
        rationale=clean_rationale(answer.rationale, valid),
    )
    return JudgeResult(view=view, model="", evidence_ids=cited)


class Judge:
    """Asks the local model, and the cloud model for uncertain items."""

    def __init__(
        self,
        local: language_models.BaseChatModel,
        local_name: str,
        cloud: language_models.BaseChatModel | None = None,
        cloud_name: str = "",
        budget: budget_lib.CloudBudget | None = None,
        band: tuple[float, float] = (0.5, 0.7),
    ) -> None:
        """Wires the models.

        Args:
            local: The main local model (``main-<profile>``).
            local_name: Its alias.
            cloud: The escalation model, or None (escalation off).
            cloud_name: Its alias (``cloud-openai``).
            budget: The monthly cloud budget; None means no cloud calls.
            band: The uncertain confidence band [low, high).
        """
        self._local = local
        self._local_name = local_name
        self._cloud = cloud
        self._cloud_name = cloud_name
        self._budget = budget
        self._band = band

    @property
    def local_name(self) -> str:
        """The local model's alias."""
        return self._local_name

    @property
    def band(self) -> tuple[float, float]:
        """The uncertain confidence band [low, high)."""
        return self._band

    def in_band(self, confidence: float) -> bool:
        """True for a confidence in the uncertain band."""
        low, high = self._band
        return low <= confidence < high

    async def can_escalate(self) -> bool:
        """True when a cloud model is set and the budget allows a call."""
        if self._cloud is None or self._budget is None:
            return False
        return await self._budget.allows()

    async def _ask(
        self,
        model: language_models.BaseChatModel,
        system: str,
        user: str,
        config: runnables.RunnableConfig,
    ) -> tuple[models.Judgement, float]:
        runnable = model.with_structured_output(
            models.Judgement, method="json_schema", include_raw=True
        )
        result: dict[str, Any] = await runnable.ainvoke(
            [("system", system), ("human", user)], config=config
        )
        cost = _cost(result.get("raw"))
        parsed = result.get("parsed")
        if result.get("parsing_error") is not None or parsed is None:
            raise JudgeError(
                f"unparsable answer: {result.get('parsing_error')}"
            )
        return parsed, cost

    async def judge(
        self,
        item: sanitize.Sanitized,
        item_id: str,
        evidence: Sequence[tuple[str, ev.Evidence]],
        config: runnables.RunnableConfig,
        *,
        cloud: bool = False,
    ) -> JudgeResult:
        """Judges one item (two tries).

        Args:
            item: The sanitized item.
            item_id: The vendor item id.
            evidence: The numbered evidence the judge may cite.
            config: The run config (Langfuse tags).
            cloud: Ask the cloud model (escalation).

        Returns:
            The checked answer.

        Raises:
            JudgeError: Two answers failed to parse or cited no evidence.
            ValueError: ``cloud`` without a cloud model.
        """
        if cloud and self._cloud is None:
            raise ValueError("no cloud model configured")
        model = self._cloud if cloud else self._local
        name = self._cloud_name if cloud else self._local_name
        valid = {ident for ident, _ in evidence}
        user = prompts.user_message(item.headline, item.body, item_id, evidence)
        system = prompts.JUDGE_SYSTEM
        total_cost = 0.0
        problem = "no answer"
        for _attempt in range(2):
            try:
                answer, cost = await self._ask(model, system, user, config)
            except (JudgeError, pydantic.ValidationError) as e:
                problem = str(e)
                _log.info("judge of %s retrying: %s", item_id, e)
                continue
            total_cost += cost
            checked = check(answer, valid)
            if checked is not None:
                if cloud and self._budget is not None:
                    await self._budget.add(total_cost)
                return dataclasses.replace(
                    checked,
                    model=name,
                    cost_usd=round(total_cost, 6),
                    escalated=cloud,
                )
            problem = "no valid evidence id cited"
            system = f"{prompts.JUDGE_SYSTEM}\n\n{_CITE_REMINDER}"
        if cloud and self._budget is not None:
            await self._budget.add(total_cost)
        raise JudgeError(f"{name}: {problem}")
