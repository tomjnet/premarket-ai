"""Output checks: no investment advice in anything the AI writes.

The AI may state sentiment (bullish, neutral, bearish) and what a story
says. It never tells anyone to buy, sell or hold, and never gives a price
target. Summaries and chat answers are checked before they're stored or
shown; the red-team eval covers the same phrases.
"""

from __future__ import annotations

import re

_ADVICE = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(you|investors|traders|one|we)\s+(should|must|could|might want "
        r"to)\s+(consider\s+)?(buy|sell|short|hold|accumulate|dump|invest)",
        r"\b(i|we)\s+(recommend|suggest|advise)\s+(buying|selling|shorting|"
        r"holding|investing|that you)",
        r"\b(buy|sell|short)\s+(the|this|these)\s+(stock|shares|dip|rally)\b",
        r"\bprice\s+target\b",
        r"\b(strong\s+)?(buy|sell|hold)\s+(rating|recommendation|signal)\b",
        r"\b(good|great|bad|smart)\s+time\s+to\s+(buy|sell|invest)\b",
        r"\bis\s+an?\s+(good|great|bad|strong|solid)\s+(buy|investment)\b",
        r"\b(go|going)\s+(long|short)\s+(on\s+)?[A-Z]",
    )
)
REFUSAL = (
    "I can't give investment advice (buy, sell or hold decisions, or price "
    "targets). Here is what the sources say instead."
)


def investment_advice(text: str) -> list[str]:
    """The advice-like phrases in ``text`` (empty when it's clean).

    Args:
        text: Model output.

    Returns:
        The matched phrases.
    """
    return [m.group() for p in _ADVICE for m in p.finditer(text)]


def asks_for_advice(question: str) -> bool:
    """True when a question asks what to buy, sell or hold."""
    return bool(
        re.search(
            r"\b(should|shall|would you|do you recommend)\b[^?]{0,40}\b(buy|"
            r"sell|short|hold|invest)\b|\bprice\s+target\b|\bgood\s+"
            r"(buy|investment)\b",
            question,
            re.IGNORECASE,
        )
    )
