"""HTML to plain text for filings and press releases (stdlib only).

Keeps the main content (``<article>``, ``<main>`` or ``id="article"`` when
the page has one), drops scripts, styles, navigation and the hidden inline
XBRL header of EDGAR filings, puts block elements on their own lines and
separates table cells with `` | ``.
"""

from __future__ import annotations

import html.parser
import re

_SKIP = frozenset(
    {
        "script",
        "style",
        "noscript",
        "nav",
        "header",
        "footer",
        "head",
        "ix:header",
        "svg",
        "form",
        "button",
    }
)
_BLOCK = frozenset(
    {
        "p",
        "div",
        "br",
        "li",
        "tr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "table",
        "section",
        "article",
        "blockquote",
        "pre",
        "ul",
        "ol",
        "title",
    }
)
_CELL = frozenset({"td", "th"})
_VOID = frozenset(
    {
        "br",
        "img",
        "hr",
        "meta",
        "link",
        "input",
        "col",
        "area",
        "base",
        "wbr",
        "source",
    }
)
_MAIN_IDS = frozenset({"article", "content", "main-content"})
_SPACES = re.compile(r"[ \t\u00a0]+")
_BLANK_LINES = re.compile(r"\n{3,}")


class _Extractor(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.main: list[str] | None = None
        self._main_depth = 0
        self._skip_depth = 0
        self._stack: list[str] = []

    def _emit(self, text: str) -> None:
        self.parts.append(text)
        if self._main_depth:
            assert self.main is not None
            self.main.append(text)

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in _VOID:
            if tag == "br":
                self._emit("\n")
            return
        self._stack.append(tag)
        if self._skip_depth or tag in _SKIP:
            self._skip_depth += 1
            return
        attr = dict(attrs)
        style = (attr.get("style") or "").replace(" ", "").lower()
        if "display:none" in style:
            self._skip_depth += 1
            return
        if self._main_depth:
            self._main_depth += 1
        elif self.main is None and (
            tag in ("article", "main") or attr.get("id") in _MAIN_IDS
        ):
            self.main = []
            self._main_depth = 1
        if tag in _BLOCK:
            self._emit("\n")
        elif tag in _CELL:
            self._emit(" | ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID or tag not in self._stack:
            return
        while self._stack:
            open_tag = self._stack.pop()
            if self._skip_depth:
                self._skip_depth -= 1
            else:
                if open_tag in _BLOCK:
                    self._emit("\n")
                if self._main_depth:
                    self._main_depth -= 1
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._emit(data)


def _tidy(text: str) -> str:
    lines = [_SPACES.sub(" ", line).strip(" |") for line in text.split("\n")]
    text = "\n".join(line.strip() for line in lines)
    return _BLANK_LINES.sub("\n\n", text).strip()


def to_text(document: str) -> str:
    """The readable text of an HTML page.

    Args:
        document: The HTML.

    Returns:
        Plain text; the page's main content when it marks one.
    """
    extractor = _Extractor()
    extractor.feed(document)
    extractor.close()
    if extractor.main:
        main = _tidy("".join(extractor.main))
        if len(main) >= 200:
            return main
    return _tidy("".join(extractor.parts))
