"""ai-api command line.

Usage:

    ai-api init                       migrations, DB role, demo users
    ai-api health                     exit 0 if the API answers /health
    ai-api openapi                    the OpenAPI document on stdout
    ai-api rules --date YYYY-MM-DD    rule checks of a feed date (no LLM)
    ai-api registry                   refresh the SEC ticker registry now
    ai-api dedup-rebuild --date YYYY-MM-DD
                                      re-index the 7-day dedup window
    ai-api enrich --date YYYY-MM-DD   first AI: L3, summaries, sentiment
    ai-api corpus                     download and index the trusted corpus
    ai-api reindex                    rebuild the vector store from Postgres
    ai-api llm-status                 the gateway's aliases, a test call
    ai-api smoke --base-url URL --date YYYY-MM-DD
                                      the increment's "done when" check

Every command except ``health`` and ``openapi`` runs as the database owner,
in the one-shot ``ai-api-init`` container.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime
import json
import logging
import os
import sys
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import zoneinfo

import psycopg

from ai_api import config
from ai_api.dedup import fastpath

# The other commands import their modules when they run: ``ai-api health``
# is the container healthcheck and must start in well under a second, and
# the app, LangChain and the rule engine take seconds to import.

_NEW_YORK = zoneinfo.ZoneInfo("America/New_York")


def _health() -> int:
    """Calls the API's /health; returns the process exit code."""
    url = os.environ.get("HEALTH_URL", "http://127.0.0.1:8000/health")
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return 0 if response.status == 200 else 1
    except OSError as error:
        print(f"health check failed: {error}", file=sys.stderr)
        return 1


def _openapi() -> int:
    """Prints the OpenAPI document (no connections are opened)."""
    from ai_api import app  # noqa: PLC0415

    settings = config.Settings(
        database=config.Database("unused", 5432, "unused", "unused", "unused"),
        redis_host="unused",
        redis_password="unused",
        jwt_secret="unused",
    )
    document = app.create_app(settings).openapi()
    print(json.dumps(document, indent=2))
    return 0


@dataclasses.dataclass
class _Reply:
    status: int
    headers: Any
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        return None


def _call(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    form: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout_s: float = 10,
) -> _Reply:
    data = None
    all_headers = {} if headers is None else dict(headers)
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        all_headers["Content-Type"] = "application/x-www-form-urlencoded"
    if body is not None:
        data = json.dumps(body).encode()
        all_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url, data=data, headers=all_headers, method=method
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout_s) as response:
            return _Reply(response.status, response.headers, response.read())
    except urllib.error.HTTPError as error:
        return _Reply(error.code, error.headers, error.read())


def _cookie(reply: _Reply) -> tuple[str, str]:
    """Returns (name=value, attributes) of the refresh cookie."""
    raw = reply.headers.get("Set-Cookie", "")
    pair, _, attributes = raw.partition(";")
    return pair.strip(), attributes.lower()


def _smoke(base_url: str, day: datetime.date) -> int:
    """Checks the website end to end, like a trader would use it.

    Args:
        base_url: The edge proxy, for example ``http://edge:8080``.
        day: The feed date: its parity run, rule run and rule results.

    Returns:
        The process exit code: 0 when every check passes.
    """
    env = os.environ
    password = config.demo_password(env)
    counts = _database_counts(day)
    api = f"{base_url.rstrip('/')}/api"
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))

    check(
        "ingest: C++20 ingester matches legacy (parity PASS)",
        counts["parity"] == "PASS",
        counts["parity_detail"],
    )
    check(
        "rules: rule run DONE for the date",
        counts["rule_run"] == "DONE",
        str(counts["rule_run"]),
    )
    check(
        "rules: catch every legacy duplicate",
        counts["rule_dups"] >= counts["legacy_dups"] > 0,
        f"rules {counts['rule_dups']} vs legacy {counts['legacy_dups']}",
    )

    page = _call("GET", f"{base_url}/")
    csp = page.headers.get("Content-Security-Policy", "")
    check("site: index.html served", page.status == 200, str(page.status))
    check("site: CSP set", "default-src 'none'" in csp, csp[:60])
    check(
        "site: framing denied",
        page.headers.get("X-Frame-Options") == "DENY",
    )
    check(
        "site: no-sniff",
        page.headers.get("X-Content-Type-Options") == "nosniff",
    )
    check(
        "api: 401 without a token",
        _call("GET", f"{api}/news").status == 401,
    )
    wrong = _call(
        "POST",
        f"{api}/auth/login",
        form={"username": "trader1", "password": "wrong-password"},
    )
    check("auth: wrong password is 401", wrong.status == 401, str(wrong.status))
    login = _call(
        "POST",
        f"{api}/auth/login",
        form={"username": "trader1", "password": password},
    )
    check("auth: login", login.status == 200, str(login.status))
    if login.status != 200:
        return _report(results)
    cookie, attributes = _cookie(login)
    check(
        "auth: refresh cookie is __Host-, HttpOnly, Secure, SameSite=Strict",
        cookie.startswith("__Host-")
        and "httponly" in attributes
        and "secure" in attributes
        and "samesite=strict" in attributes,
        attributes,
    )
    token = login.json()["access_token"]
    bearer = {"Authorization": f"Bearer {token}"}

    feed = _call("GET", f"{api}/news?date={day.isoformat()}", bearer)
    check("news: feed", feed.status == 200, str(feed.status))
    if feed.status == 200:
        body = feed.json()
        run = body["run"]
        check(
            "news: run is DONE",
            run is not None and run["status"] == "DONE",
            "no run" if run is None else run["status"],
        )
        unique = counts["items"] - counts["rule_dups"]
        check(
            "news: every unique story, rule duplicates hidden",
            body["count"] == unique > 0,
            f"web {body['count']} vs {unique} unique"
            f" (PDF {counts['pdf_rows']})",
        )
        codes = {
            code for item in body["items"] for code in item["reason_codes"]
        }
        check(
            "news: FAKE COMPANY / FAKE TICKER badges without any LLM",
            {"FAKE_COMPANY", "FAKE_TICKER"} <= codes,
            ", ".join(sorted(codes)) or "no reason codes",
        )
        if body["items"]:
            first = body["items"][0]["id"]
            detail = _call("GET", f"{api}/news/{first}", bearer)
            check(
                "news: detail has the body and rule evidence",
                detail.status == 200
                and bool(detail.json().get("body"))
                and bool(detail.json().get("rule_evidence")),
            )
    _smoke_ai(check, api, bearer, day, counts)
    check(
        "news: unknown id is 404",
        _call("GET", f"{api}/news/999999999999", bearer).status == 404,
    )
    cross_site = _call(
        "POST",
        f"{api}/auth/refresh",
        {"Cookie": cookie, "Origin": "https://evil.example"},
    )
    check("csrf: cross-site refresh is 403", cross_site.status == 403)
    refreshed = _call("POST", f"{api}/auth/refresh", {"Cookie": cookie})
    new_cookie, _ = _cookie(refreshed)
    check(
        "auth: refresh rotates the cookie",
        refreshed.status == 200 and new_cookie and new_cookie != cookie,
    )
    logout = _call("POST", f"{api}/auth/logout", {"Cookie": new_cookie})
    check("auth: logout", logout.status == 204, str(logout.status))
    check(
        "auth: access token revoked by logout",
        _call("GET", f"{api}/news", bearer).status == 401,
    )
    return _report(results)


def _sse_events(body: bytes) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in body.decode().split("\n\n"):
        name, data = "message", ""
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data += line[len("data: ") :]
        if data:
            events.append((name, json.loads(data)))
    return events


def _chat_done(
    api: str, bearer: dict[str, str], question: str, day: datetime.date
) -> tuple[int, dict[str, Any]]:
    reply = _call(
        "POST",
        f"{api}/chat",
        bearer,
        body={"question": question, "date": day.isoformat()},
        timeout_s=300,
    )
    done: dict[str, Any] = {}
    if reply.status == 200:
        for name, data in _sse_events(reply.body):
            if name == "done":
                done = data
    return reply.status, done


def _smoke_ai(
    check: Any,
    api: str,
    bearer: dict[str, str],
    day: datetime.date,
    counts: dict[str, Any],
) -> None:
    """Increment 3: summaries for every unique item, cited chat answers."""
    check(
        "ai: AI run DONE for the date",
        counts["ai_run"] == "DONE",
        str(counts["ai_run"]),
    )
    check(
        "ai: every unique English item has a summary",
        counts["to_summarize"] > 0
        and counts["summarized"] == counts["to_summarize"],
        f"{counts['summarized']} of {counts['to_summarize']}"
        f" ({counts['fallbacks']} fallback)",
    )
    feed = _call("GET", f"{api}/news?date={day.isoformat()}", bearer)
    if feed.status == 200:
        items = feed.json()["items"]
        shown = sum(1 for i in items if i["summary"] and i["sentiment"])
        check(
            "news: the feed shows the summaries and sentiment",
            bool(items) and shown >= len(items) - counts["skipped"],
            f"{shown} of {len(items)} with a summary",
        )
        if items:
            detail = _call("GET", f"{api}/news/{items[0]['id']}", bearer)
            ai = detail.json().get("ai") if detail.status == 200 else None
            check(
                "news: detail has the extraction (companies, claims)",
                ai is not None and bool(ai["companies"]),
            )
    status, done = _chat_done(
        api,
        bearer,
        "What did the Federal Reserve decide about interest rates at its"
        " latest meeting?",
        day,
    )
    check(
        "chat: the answer cites a trusted source",
        bool(done.get("cites_trusted")),
        f"HTTP {status}, citations {done.get('citations')}",
    )
    status, done = _chat_done(api, bearer, "Should I buy NVDA today?", day)
    answer = str(done.get("answer", ""))
    check(
        'chat: "Should I buy NVDA?" gets no investment advice',
        "investment advice" in answer.lower(),
        f"HTTP {status}: {answer[:70]}",
    )


def _database_counts(day: datetime.date) -> dict[str, Any]:
    """What the smoke check compares the website with (as the owner)."""
    owner = config.Database.from_env(os.environ, "PGUSER", "PGPASSWORD")
    counts: dict[str, Any] = {}
    with psycopg.connect(owner.dsn()) as conn:
        row = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE is_dup),"
            " count(*) FILTER (WHERE NOT is_dup)"
            " FROM ai.v_raw_news WHERE feed_date = %s",
            (day,),
        ).fetchone()
        counts["items"], counts["legacy_dups"], counts["pdf_rows"] = row
        row = conn.execute(
            "SELECT count(*) FROM ai.duplicate_link d"
            " JOIN ai.news_item n ON n.id = d.news_id WHERE n.feed_date = %s",
            (day,),
        ).fetchone()
        counts["rule_dups"] = row[0]
        row = conn.execute(
            "SELECT status FROM ai.rule_run WHERE feed_date = %s"
            " ORDER BY started_at DESC LIMIT 1",
            (day,),
        ).fetchone()
        counts["rule_run"] = None if row is None else row[0]
        row = conn.execute(
            "SELECT status FROM ai.ai_run WHERE feed_date = %s"
            " ORDER BY started_at DESC LIMIT 1",
            (day,),
        ).fetchone()
        counts["ai_run"] = None if row is None else row[0]
        row = conn.execute(
            "SELECT count(*) FILTER (WHERE a.status IN ('DONE', 'FAILED')),"
            " count(*) FILTER (WHERE a.summary IS NOT NULL),"
            " count(*) FILTER (WHERE a.summary_source = 'fallback'),"
            " count(*) FILTER (WHERE a.status = 'SKIPPED')"
            " FROM ai.news_ai a JOIN ai.news_item n ON n.id = a.news_id"
            " WHERE n.feed_date = %s",
            (day,),
        ).fetchone()
        (
            counts["to_summarize"],
            counts["summarized"],
            counts["fallbacks"],
            counts["skipped"],
        ) = row
        try:
            row = conn.execute(
                "SELECT status, differences, legacy_rows, modern_rows"
                " FROM ingest.parity_run WHERE feed_date = %s"
                " ORDER BY checked_at DESC LIMIT 1",
                (day,),
            ).fetchone()
        except psycopg.errors.UndefinedTable:
            row = None
    if row is None:
        counts["parity"] = None
        counts["parity_detail"] = "no parity run: make -C python parity"
    else:
        counts["parity"] = row[0]
        counts["parity_detail"] = (
            f"{row[1]} differences, legacy {row[2]} vs modern {row[3]} rows"
        )
    return counts


def _rules(day: datetime.date) -> int:
    from ai_api.rules import runner  # noqa: PLC0415

    settings = config.RulesSettings.from_env(os.environ)
    try:
        asyncio.run(runner.run(settings, day))
    except runner.NotReadyError as e:
        print(f"rules: {e}", file=sys.stderr)
        return 1
    return 0


def _registry() -> int:
    from ai_api.rules import runner  # noqa: PLC0415

    settings = config.RulesSettings.from_env(os.environ)
    tickers = asyncio.run(runner.refresh_registry(settings))
    print(f"SEC ticker registry: {tickers} tickers")
    return 0 if tickers else 1


def _dedup_rebuild(day: datetime.date) -> int:
    from ai_api.rules import runner  # noqa: PLC0415

    settings = config.RulesSettings.from_env(os.environ)
    indexed = asyncio.run(runner.rebuild_index(settings, day))
    print(f"dedup index: {indexed} unique items re-indexed")
    return 0


def _enrich(day: datetime.date) -> int:
    from ai_api.enrich import runner as enrich_runner  # noqa: PLC0415

    settings = config.AiSettings.from_env(os.environ)
    try:
        counts = asyncio.run(enrich_runner.run(settings, day))
    except enrich_runner.NotReadyError as e:
        print(f"enrich: {e}", file=sys.stderr)
        return 1
    print(f"enrich {day}: {counts.line()}")
    return 1 if counts.failed else 0


def _corpus() -> int:
    from ai_api.rag import corpus  # noqa: PLC0415

    settings = config.AiSettings.from_env(os.environ)
    try:
        counts = asyncio.run(corpus.build(settings))
    except corpus.CorpusError as e:
        print(f"corpus: {e}", file=sys.stderr)
        return 1
    print(
        f"corpus: {counts.fetched} fetched, {counts.changed} new or changed,"
        f" {counts.chunks_indexed} chunks indexed; total {counts.documents}"
        f" documents, {counts.chunks} chunks; {counts.failures} failures"
    )
    return 0 if counts.chunks else 1


def _reindex() -> int:
    from ai_api.rag import corpus  # noqa: PLC0415

    settings = config.AiSettings.from_env(os.environ)
    print(f"reindex: {asyncio.run(corpus.reindex(settings))} chunks indexed")
    return 0


def _llm_status() -> int:
    """Lists the gateway's aliases and makes one small call per task."""
    from ai_api.llm import factory  # noqa: PLC0415

    llm = config.AiSettings.from_env(os.environ).llm
    reply = _call(
        "GET",
        f"{llm.gateway_url}/models",
        {"Authorization": f"Bearer {llm.api_key}"},
    )
    if reply.status != 200:
        print(f"gateway: HTTP {reply.status}", file=sys.stderr)
        return 1
    aliases = sorted(model["id"] for model in reply.json()["data"])
    print(f"gateway {llm.gateway_url}: {len(aliases)} aliases")
    print(
        f"profile {llm.hw_profile}: main={llm.main_model}"
        f" embed={llm.embed_model} ({llm.embed_dims} dims)"
    )
    started = time.monotonic()
    vector = factory.embeddings(llm).embed_query(llm.query_prefix + "ping")
    print(f"embed: {len(vector)} dims ({time.monotonic() - started:.1f} s)")
    started = time.monotonic()
    answer = factory.chat_model(llm, max_tokens=5).invoke("Reply with: ok")
    text = str(answer.content).strip()[:40]
    print(f"main: {text!r} ({time.monotonic() - started:.1f} s)")
    return 0 if len(vector) == llm.embed_dims else 1


def _report(results: list[tuple[str, bool, str]]) -> int:
    for name, ok, detail in results:
        suffix = f"  ({detail})" if detail else ""
        print(f"{'PASS' if ok else 'FAIL'}  {name}{suffix}")
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    """Runs one ai-api command.

    Args:
        argv: The arguments after the program name. None means
            ``sys.argv[1:]``.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(prog="ai-api")
    parser.add_argument(
        "command",
        choices=(
            "init",
            "health",
            "openapi",
            "rules",
            "registry",
            "dedup-rebuild",
            "enrich",
            "corpus",
            "reindex",
            "llm-status",
            "smoke",
        ),
    )
    parser.add_argument("--base-url", default="http://edge:8080")
    parser.add_argument(
        "--date", type=datetime.date.fromisoformat, default=None
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        if args.command == "health":
            return _health()
        if args.command == "openapi":
            return _openapi()
        if args.command == "init":
            from ai_api import bootstrap  # noqa: PLC0415

            bootstrap.run(os.environ)
            return 0
        if args.command == "registry":
            return _registry()
        if args.command == "corpus":
            return _corpus()
        if args.command == "reindex":
            return _reindex()
        if args.command == "llm-status":
            return _llm_status()
        day = args.date
        if day is None:
            day = datetime.datetime.now(_NEW_YORK).date()
        if args.command == "rules":
            return _rules(day)
        if args.command == "dedup-rebuild":
            return _dedup_rebuild(day)
        if args.command == "enrich":
            return _enrich(day)
        return _smoke(args.base_url, day)
    except (config.ConfigError, fastpath.FastpathMissingError) as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
