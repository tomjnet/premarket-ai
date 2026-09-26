"""fetch_url: SSRF checks, robots.txt, redirects, text extraction."""

import asyncio

import httpx
import pytest

from mcp_server import fetch


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.9",
        "192.168.1.20",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
    ],
)
def test_private_addresses_are_refused(address):
    with pytest.raises(fetch.FetchError):
        fetch.check_address(address)


def test_public_addresses_pass():
    fetch.check_address("93.184.216.34")
    fetch.check_address("2606:4700::1111")


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://example.com/",
        "http://user:pw@example.com/",
        "http://example.com:8080/",
        "https:///nohost",
    ],
)
def test_bad_urls_are_refused(url):
    with pytest.raises(fetch.FetchError):
        fetch.check_url(url)


def test_page_text_skips_scripts_and_navigation():
    title, text = fetch.page_text(
        "<html><head><title> Apple  news </title><script>x()</script></head>"
        "<body><nav>Menu</nav><h1>Dividend</h1><p>Apple raised it.</p>"
        "</body></html>"
    )
    assert title == "Apple news"
    assert text == "Dividend\nApple raised it."


def _fetcher(monkeypatch, handler, addresses=None):
    async def resolve(host):
        found = (addresses or {}).get(host, ["93.184.216.34"])
        for address in found:
            fetch.check_address(address)
        return found

    monkeypatch.setattr(fetch, "resolve", resolve)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return fetch.Fetcher(client, max_bytes=1000)


def test_a_page_is_fetched_as_text(monkeypatch):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<title>T</title><p>Body</p>",
        )

    fetcher = _fetcher(monkeypatch, handler)
    found = asyncio.run(fetcher.fetch("https://news.example.com/a"))
    assert found == {
        "url": "https://news.example.com/a",
        "status": 200,
        "title": "T",
        "text": "Body",
        "truncated": False,
    }


def test_robots_txt_is_honored(monkeypatch):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /")
        raise AssertionError("fetched a disallowed page")

    fetcher = _fetcher(monkeypatch, handler)
    with pytest.raises(fetch.FetchError, match="robots"):
        asyncio.run(fetcher.fetch("https://news.example.com/a"))


def test_a_redirect_to_a_private_host_is_refused(monkeypatch):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "http://internal/"})

    fetcher = _fetcher(monkeypatch, handler, {"internal": ["10.0.0.5"]})
    with pytest.raises(fetch.FetchError, match="not a public address"):
        asyncio.run(fetcher.fetch("https://news.example.com/a"))


def test_big_and_binary_pages_are_refused(monkeypatch):
    def big(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="x" * 5000)

    with pytest.raises(fetch.FetchError, match="larger"):
        asyncio.run(_fetcher(monkeypatch, big).fetch("https://e.com/a"))

    def binary(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200, headers={"content-type": "application/pdf"}, content=b"%PDF"
        )

    with pytest.raises(fetch.FetchError, match="not a text page"):
        asyncio.run(_fetcher(monkeypatch, binary).fetch("https://e.com/a"))


def test_a_404_is_an_answer_not_an_error(monkeypatch):
    def handler(request):
        return httpx.Response(404)

    found = asyncio.run(
        _fetcher(monkeypatch, handler).fetch("https://e.com/gone")
    )
    assert (found["status"], found["text"]) == (404, "")
