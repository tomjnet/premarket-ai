"""``fetch_url``: one web page as plain text, SSRF-protected.

A cited URL that doesn't exist, or doesn't say what the item claims, is a
strong fake-news signal. The page is fetched, reduced to text, returned
and discarded (only the Redis cache keeps it, for an hour). Protections:

- only ``http``/``https`` on ports 80 and 443, no user info in the URL;
- every address the host resolves to must be public: private, loopback,
  link-local, multicast, reserved and shared (CGNAT) ranges are refused,
  and the address the connection actually reached is checked again (DNS
  rebinding);
- at most 3 redirects, each checked the same way;
- ``robots.txt`` is honored;
- 10 s per request, at most ``FETCH_MAX_BYTES``, HTML or plain text only.

(Crawl4AI, the plan's first choice, drives a headless browser: too heavy
for this read-only 256 MB container, and a single page's text is all the
tool returns.)
"""

from __future__ import annotations

import asyncio
import html.parser
import ipaddress
import socket
from typing import Any
import urllib.parse
import urllib.robotparser

import httpx

USER_AGENT = "premarket-ai-lab/0.1 (+research; read-only)"
_MAX_REDIRECTS = 3
_TIMEOUT_S = 10.0
_MAX_TEXT_CHARS = 6000
_TEXT_TYPES = ("text/html", "text/plain", "application/xhtml+xml")
_SKIP_TAGS = frozenset(
    {"script", "style", "noscript", "template", "svg", "head", "nav", "footer"}
)
_BLOCKS = frozenset(
    {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"}
)


class FetchError(RuntimeError):
    """The URL is not allowed, or the fetch failed."""


def check_address(address: str) -> None:
    """Refuses any address that isn't public.

    Raises:
        FetchError: A private, loopback, link-local, multicast, reserved,
            unspecified or shared address.
    """
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if not ip.is_global or ip.is_multicast:
        raise FetchError(f"{address} is not a public address")


def check_url(url: str) -> urllib.parse.SplitResult:
    """Scheme, port and user-info checks (before any DNS lookup).

    Raises:
        FetchError: The URL is not an allowed one.
    """
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise FetchError("only http and https URLs")
    if not parts.hostname:
        raise FetchError("the URL has no host")
    if parts.username or parts.password:
        raise FetchError("user info in URLs is not allowed")
    try:
        port = parts.port
    except ValueError as e:
        raise FetchError("bad port") from e
    if port not in (None, 80, 443):
        raise FetchError("only ports 80 and 443")
    return parts


async def resolve(host: str) -> list[str]:
    """Every address of ``host``, all checked.

    Raises:
        FetchError: It doesn't resolve, or an address isn't public.
    """
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, None, type=socket.SOCK_STREAM
        )
    except OSError as e:
        raise FetchError(f"{host} doesn't resolve") from e
    addresses = sorted({info[4][0] for info in infos})
    for address in addresses:
        check_address(address)
    return addresses


class _Text(html.parser.HTMLParser):
    """Visible text and the title of an HTML page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        del attrs
        if tag == "title":
            self._in_title = True
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def page_text(document: str) -> tuple[str, str]:
    """(title, text) of an HTML page; text collapsed to lines."""
    parser = _Text()
    parser.feed(document)
    lines = (
        " ".join(line.split()) for line in "".join(parser.parts).split("\n")
    )
    text = "\n".join(line for line in lines if line)
    return " ".join(parser.title.split()), text


class Fetcher:
    """Fetches pages with the protections of the module docstring."""

    def __init__(
        self, http: httpx.AsyncClient, max_bytes: int = 1_000_000
    ) -> None:
        """Uses ``http`` (no redirects followed by the client itself)."""
        self._http = http
        self._max_bytes = max_bytes

    async def _get(self, url: str, limit: int) -> tuple[httpx.Response, bytes]:
        parts = check_url(url)
        await resolve(parts.hostname or "")
        async with self._http.stream(
            "GET",
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5"},
            timeout=_TIMEOUT_S,
            follow_redirects=False,
        ) as response:
            stream = response.extensions.get("network_stream")
            if stream is not None:
                peer = stream.get_extra_info("server_addr")
                if peer:
                    check_address(str(peer[0]))
            body = b""
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > limit:
                    raise FetchError(f"larger than {limit} bytes")
            return response, body

    async def _allowed(self, parts: urllib.parse.SplitResult) -> bool:
        robots = f"{parts.scheme}://{parts.netloc}/robots.txt"
        try:
            response, body = await self._get(robots, 200_000)
        except (FetchError, httpx.HTTPError):
            return True
        if response.status_code >= 400:
            return True
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(body.decode("utf-8", "replace").splitlines())
        return parser.can_fetch(USER_AGENT, urllib.parse.urlunsplit(parts))

    async def fetch(self, url: str) -> dict[str, Any]:
        """The page's title and text.

        Args:
            url: An absolute http(s) URL.

        Returns:
            ``url`` (after redirects), ``status``, ``title``, ``text`` (at
            most 6000 characters) and ``truncated``; for an error status
            (a 404 is a signal too) the text is empty.

        Raises:
            FetchError: Not allowed, blocked by robots.txt, not text, too
                large, or unreachable.
        """
        current = url.strip()
        for _hop in range(_MAX_REDIRECTS + 1):
            parts = check_url(current)
            if not await self._allowed(parts):
                raise FetchError("robots.txt disallows this page")
            try:
                response, body = await self._get(current, self._max_bytes)
            except httpx.HTTPError as e:
                raise FetchError(f"unreachable: {e!r}") from e
            if response.is_redirect:
                location = response.headers.get("location", "")
                current = urllib.parse.urljoin(current, location)
                continue
            break
        else:
            raise FetchError(f"more than {_MAX_REDIRECTS} redirects")
        if response.status_code >= 400:
            return {
                "url": current,
                "status": response.status_code,
                "title": "",
                "text": "",
                "truncated": False,
            }
        kind = response.headers.get("content-type", "").split(";")[0].strip()
        if kind not in _TEXT_TYPES:
            raise FetchError(f"not a text page ({kind or 'no content type'})")
        charset = response.charset_encoding or "utf-8"
        document = body.decode(charset, "replace")
        if kind == "text/plain":
            title, text = "", document
        else:
            title, text = page_text(document)
        return {
            "url": current,
            "status": response.status_code,
            "title": title[:300],
            "text": text[:_MAX_TEXT_CHARS],
            "truncated": len(text) > _MAX_TEXT_CHARS,
        }
