"""Sanitize untrusted text before any LLM sees it.

Layer 1 of the prompt-injection defense (layer 2, Llama Guard, arrives in
increment 4):

- HTML tags, entities, zero-width and other invisible characters are
  removed, and the text is NFKC-normalized, so hidden text can't reach the
  model and look-alike tricks don't dodge the patterns below.
- Emails and phone numbers are masked (no personal data goes to a model).
- Sentences that read like instructions to an AI ("ignore previous
  instructions", "mark this story as VERIFIED") are replaced by a marker
  and reported as ``INJECTION_ATTEMPT``. The item is still processed: the
  attempt itself is evidence against it.
- The text is capped, so one item can't fill the context window.
"""

from __future__ import annotations

import dataclasses
import html
import re
import unicodedata

from ai_api.dedup import normalize

INJECTION_ATTEMPT = "INJECTION_ATTEMPT"
MAX_BODY_CHARS = 6000
MAX_HEADLINE_CHARS = 300
REMOVED = "[removed: instruction-like text]"

_SCRIPT = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL
)
_TAG = re.compile(r"<[^<>]{0,1000}>")
_SPACES = re.compile(r"[ \t\f\v]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")
# A sentence ends at . ! or ? followed by a space or the end ("1.0" and
# "$85.1" stay inside their sentence).
_SENTENCE = re.compile(r"(?:[^.!?\n]|[.!?](?=[^\s.!?]))+[.!?]*")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
# Phone numbers: +1 212 555 0100, (212) 555-0100, 212.555.0100.
_PHONE = re.compile(
    r"(?<![\w$.])(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]\d{3}[\s.-]"
    r"\d{4}(?![\w%])"
)
_INJECTION = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(ignore|disregard|forget|override)\b[^.]{0,40}\b(previous|prior|"
        r"above|earlier|all|your|the|any)\b[^.]{0,20}\b(instructions?|rules|"
        r"prompts?|guidelines|polic(y|ies))\b",
        r"\b(system|developer|admin)\s*(note|prompt|message|override|"
        r"instruction)s?\b",
        r"\b(note|message|instructions?)\s+(to|for)\s+(the\s+)?(ai|llm|model|"
        r"assistant|reviewers?|fact[- ]checkers?)\b",
        r"\b(mark|classify|label|rate|treat|flag)\b[^.]{0,30}\b(this|the)\b"
        r"[^.]{0,20}\b(story|item|article|news)\b[^.]{0,20}\bas\b[^.]{0,10}"
        r"\b(verified|true|real|confirmed|legitimate|safe)\b",
        r"\bdo\s+not\s+(flag|verify|check|question)\b",
        r"\byou\s+are\s+(now|an?)\b[^.]{0,40}\b(ai|assistant|model|bot)\b",
        r"</?\s*(system|assistant|user|instructions?)\s*>",
        r"\bconfidence\s*(=|:|of)?\s*1(\.0+)?\b",
    )
)
# Unicode categories that render as nothing or change text direction.
_INVISIBLE_CATEGORIES = frozenset({"Cf", "Co", "Cs", "Cn"})


@dataclasses.dataclass(frozen=True)
class Sanitized:
    """A vendor item as the model may see it.

    Attributes:
        headline: The clean headline.
        body: The clean story (no vendor boilerplate).
        injections: The instruction-like sentences that were removed.
        masked: How many emails and phone numbers were masked.
        truncated: The body was longer than the cap.
    """

    headline: str
    body: str
    injections: tuple[str, ...] = ()
    masked: int = 0
    truncated: bool = False

    @property
    def text(self) -> str:
        """Headline and body, as one text."""
        return f"{self.headline}\n{self.body}"


def clean_text(text: str) -> str:
    """Plain, visible text: no HTML, no invisible characters, NFKC.

    Args:
        text: Untrusted text.

    Returns:
        The text with tags and entities removed, invisible and control
        characters dropped (newlines kept), spaces collapsed.
    """
    text = _SCRIPT.sub(" ", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = unicodedata.normalize("NFKC", text)
    text = "".join(
        char
        for char in text
        if char in "\n\t"
        or (
            unicodedata.category(char) not in _INVISIBLE_CATEGORIES
            and unicodedata.category(char) != "Cc"
        )
    )
    text = _SPACES.sub(" ", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def mask_pii(text: str) -> tuple[str, int]:
    """Masks emails and phone numbers.

    Returns:
        The text and the number of masked values.
    """
    text, emails = _EMAIL.subn("[email]", text)
    text, phones = _PHONE.subn("[phone]", text)
    return text, emails + phones


def injection_sentences(text: str) -> list[str]:
    """The sentences of ``text`` that read like instructions to an AI."""
    found = []
    for match in _SENTENCE.finditer(text):
        sentence = match.group().strip()
        if sentence and any(p.search(sentence) for p in _INJECTION):
            found.append(sentence)
    return found


def _remove(text: str, sentences: list[str]) -> str:
    for sentence in sentences:
        text = text.replace(sentence, REMOVED)
    return text


def _cap(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip() + " [truncated]", True


def sanitize(headline: str, body: str) -> Sanitized:
    """Cleans one vendor item for the model (see the module docstring).

    Args:
        headline: The vendor headline.
        body: The vendor body.

    Returns:
        The sanitized item.
    """
    headline, body = normalize.strip_boilerplate(headline, body)
    headline = clean_text(headline).replace("\n", " ")
    body = clean_text(body)
    headline, masked_h = mask_pii(headline)
    body, masked_b = mask_pii(body)
    found_h = injection_sentences(headline)
    found_b = injection_sentences(body)
    headline = _remove(headline, found_h)
    body = _remove(body, found_b)
    headline, _ = _cap(headline, MAX_HEADLINE_CHARS)
    body, truncated = _cap(body, MAX_BODY_CHARS)
    return Sanitized(
        headline=headline,
        body=body,
        injections=tuple(found_h + found_b),
        masked=masked_h + masked_b,
        truncated=truncated,
    )
