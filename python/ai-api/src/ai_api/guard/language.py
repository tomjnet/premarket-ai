"""English only: a small, deterministic language check.

The models, prompts and evals are English. A non-English item skips the
LLM steps and is flagged ``UNSUPPORTED_LANGUAGE`` instead of being
summarized in a language nobody checked. The check counts common English
function words, which is enough for news paragraphs; very short texts are
given the benefit of the doubt.
"""

from __future__ import annotations

import re

UNSUPPORTED_LANGUAGE = "UNSUPPORTED_LANGUAGE"
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_MIN_WORDS = 8
_MIN_ENGLISH_SHARE = 0.12
_MIN_LATIN_SHARE = 0.8
_FUNCTION_WORDS = """
a an the and or but if of to in on at by for with from as into over
after before about than that this these those it its is are was were be
been has have had will would can could may said says not no their
his her they we he she which who what when while also up down out new
per year years quarter company shares
"""
_ENGLISH = frozenset(_FUNCTION_WORDS.split())


def is_english(text: str) -> bool:
    """True when ``text`` reads as English.

    Args:
        text: Plain text.

    Returns:
        True for English, or for text too short to tell.
    """
    words = [word.lower() for word in _WORD.findall(text)]
    if len(words) < _MIN_WORDS:
        return True
    latin = sum(1 for word in words if word.isascii())
    if latin / len(words) < _MIN_LATIN_SHARE:
        return False
    english = sum(1 for word in words if word in _ENGLISH)
    return english / len(words) >= _MIN_ENGLISH_SHARE
