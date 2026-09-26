"""Guard layer 2: Llama Guard 3 on untrusted text (the ``guard-*`` alias).

Llama Guard reads a conversation and answers ``safe``, or ``unsafe`` and
the hazard categories on the next line (``S1``, ``S10``...). It runs on
vendor news before the judge sees it, and on chat questions and answers.
It classifies harmful content; instruction-like text is layer 1's job
(``sanitize``), so an injection attempt can still be "safe" here.

Measured on the GTX 1650 with ``llama-guard3:1b`` (2026-09-26): chat
questions and answers are classified as intended ("How do I make a
bomb?" S1, "Should I buy NVDA?" S6, the rest safe), but plain financial
news is flagged S1 or S5 whatever the framing. So on news the verdict is
evidence only unless GUARD_NEWS_REVIEW is on (for the 8B guard of the
bigger profiles). A news item is sent as the agent's turn of "report
today's news": content to classify, not a user's request. In chat, S6
(specialized advice) alone doesn't block: the app's own no-advice policy
answers those questions with a refusal and the facts.

When the guard model can't be reached, the result says so: news items are
still verified (they are sanitized and spotlighted), and the evidence
records that the guard didn't run.
"""

from __future__ import annotations

import dataclasses
import logging
import re

from langchain_core import language_models

_log = logging.getLogger(__name__)
# Llama Guard 3's hazard taxonomy (MLCommons).
CATEGORIES = {
    "S1": "violent crimes",
    "S2": "non-violent crimes",
    "S3": "sex-related crimes",
    "S4": "child sexual exploitation",
    "S5": "defamation",
    "S6": "specialized advice",
    "S7": "privacy",
    "S8": "intellectual property",
    "S9": "indiscriminate weapons",
    "S10": "hate",
    "S11": "suicide and self-harm",
    "S12": "sexual content",
    "S13": "elections",
    "S14": "code interpreter abuse",
}
# Specialized advice (financial advice included): the chat's own no-advice
# policy handles it, so it never blocks a question on its own.
ADVICE_CATEGORY = "S6"
_NEWS_REQUEST = "Report today's news item."
_CATEGORY = re.compile(r"\bS\d{1,2}\b")
_MAX_CHARS = 6000


@dataclasses.dataclass(frozen=True)
class Verdict:
    """What Llama Guard said.

    Attributes:
        ran: False when the guard model couldn't be reached.
        safe: True for ``safe`` (and when it didn't run).
        categories: The hazard codes of an ``unsafe`` answer.
    """

    ran: bool
    safe: bool = True
    categories: tuple[str, ...] = ()

    def blocks_question(self) -> bool:
        """Unsafe for anything but specialized advice (see module doc)."""
        return (
            self.ran
            and not self.safe
            and set(self.categories) != {ADVICE_CATEGORY}
        )

    def describe(self) -> str:
        """``safe``, ``unsafe: S5 (defamation)`` or ``not run``."""
        if not self.ran:
            return "not run (guard model unavailable)"
        if self.safe:
            return "safe"
        names = ", ".join(
            f"{c} ({CATEGORIES.get(c, 'unknown')})" for c in self.categories
        )
        return f"unsafe: {names or 'no category given'}"

    def to_json(self) -> dict:
        """The verdict as the graph state carries it."""
        return {
            "ran": self.ran,
            "safe": self.safe,
            "categories": list(self.categories),
        }

    @classmethod
    def from_json(cls, data: dict | None) -> Verdict:
        """Rebuilds a verdict stored by ``to_json``; None means not run."""
        if not data:
            return cls(ran=False)
        return cls(
            bool(data["ran"]), bool(data["safe"]), tuple(data["categories"])
        )


def parse(answer: str) -> Verdict:
    """Parses Llama Guard's answer.

    Args:
        answer: ``safe``, or ``unsafe`` with categories on the next line.

    Returns:
        The verdict; anything that isn't clearly ``safe`` is unsafe.
    """
    text = answer.strip()
    first = text.split("\n", 1)[0].strip().lower()
    if first == "safe":
        return Verdict(ran=True)
    return Verdict(
        ran=True, safe=False, categories=tuple(_CATEGORY.findall(text))
    )


class Guard:
    """Llama Guard through the gateway."""

    def __init__(self, model: language_models.BaseChatModel | None) -> None:
        """Uses ``model`` (the ``guard-*`` alias); None turns it off."""
        self._model = model

    @property
    def enabled(self) -> bool:
        """True when a guard model is configured."""
        return self._model is not None

    async def _classify(self, messages: list[tuple[str, str]]) -> Verdict:
        if self._model is None:
            return Verdict(ran=False)
        try:
            answer = await self._model.ainvoke(messages)
        except Exception as e:  # noqa: BLE001 - the guard must never crash.
            _log.warning("Llama Guard unavailable: %r", e)
            return Verdict(ran=False)
        content = answer.content if isinstance(answer.content, str) else ""
        return parse(content)

    async def check_news(self, headline: str, body: str) -> Verdict:
        """Classifies a vendor item (the agent's turn; see module doc)."""
        text = f"{headline}\n{body}"[:_MAX_CHARS]
        return await self._classify([("human", _NEWS_REQUEST), ("ai", text)])

    async def check_question(self, question: str) -> Verdict:
        """Classifies a chat question before it reaches the main model."""
        return await self._classify([("human", question[:_MAX_CHARS])])

    async def check_answer(self, question: str, answer: str) -> Verdict:
        """Classifies a chat answer (the assistant turn)."""
        return await self._classify(
            [
                ("human", question[:_MAX_CHARS]),
                ("ai", answer[:_MAX_CHARS]),
            ]
        )
