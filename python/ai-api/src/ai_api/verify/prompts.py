"""The LLM judge's prompt. Changing it bumps ``PROMPT_VERSION``.

Same structure as the increment 3 prompts: the task, the spotlighting rule,
the output rules, then the data blocks. The evidence goes in ``<source>``
blocks (untrusted too: some of it quotes the item), numbered E1, E2...
"""

from __future__ import annotations

from collections.abc import Sequence

from ai_api.guard import spotlight
from ai_api.verify import evidence as ev

PROMPT_VERSION = "verify-v1"

JUDGE_SYSTEM = f"""\
You are the last step of a fact-checking pipeline for pre-market news.
{spotlight.DATA_RULES}

You get one vendor news item and numbered evidence (E1, E2, ...) that
deterministic checks already collected: the SEC ticker registry, the
source's reputation, searches of SEC filings and the web, and checks of the
numbers and the headline. Choose one of three verdicts:
- VERIFIED: a real company, and the story is corroborated: by a primary
  source, by two independent trusted outlets or, in this lab, by one
  trusted-tier newswire with every check clean. No number contradicts the
  evidence.
- UNVERIFIED: nothing contradicts the story, but it is not corroborated
  enough yet. It may be real breaking news.
- MISLEADING: the company is real and the story is partly true, but key
  facts are wrong: a number doesn't match, old news is presented as new, or
  the headline exaggerates the body.
Rules decide FAKE before you; FAKE is not one of your choices.

Return JSON that matches the schema:
- verdict and confidence (0 to 1).
- reason_codes: only codes the evidence supports (NUMBER_MISMATCH,
  SENSATIONAL_HEADLINE, STALE, NO_CORROBORATION, CONFLICTING_VERSION).
- evidence_ids: the ids of the evidence you relied on, at least one.
- rationale: at most two sentences in English that cite evidence ids in
  brackets, like [E2].
Judge only from the item and the evidence. Never give investment advice."""


def user_message(
    headline: str,
    body: str,
    item_id: str,
    evidence: Sequence[tuple[str, ev.Evidence]],
) -> str:
    """The item and its numbered evidence, as data blocks.

    Args:
        headline: The sanitized headline.
        body: The sanitized body.
        item_id: The vendor item id.
        evidence: (id, evidence) pairs, for example ("E1", ...).

    Returns:
        The user message.
    """
    blocks = [spotlight.news_block(headline, body, item_id)]
    for ident, item in evidence:
        code = f" ({item.code})" if item.code else ""
        title = f"{item.check} check{code}"
        blocks.append(spotlight.source_block(ident, title, item.message))
    return "\n\n".join(blocks)
