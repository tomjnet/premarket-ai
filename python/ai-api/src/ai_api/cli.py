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
    ai-api verify --date YYYY-MM-DD   queue a verify run, follow it to the end
    ai-api expire --date YYYY-MM-DD   market open: pending reviews expire
    ai-api ml-train                   fine-tune the DistilBERT baseline
    ai-api smoke --base-url URL --date YYYY-MM-DD
                                      the increment's "done when" check

Every command except ``health``, ``openapi`` and ``ml-train`` runs as the
database owner, in the one-shot ``ai-api-init`` container (``ml-train``
runs in the ``ai-eval`` image, which has vendor-sim's generator and torch).
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime
import json
import logging
import os
import pathlib
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
    _smoke_verify(check, api, bearer, day, counts, password)
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


def _login(api: str, username: str, password: str) -> dict[str, str]:
    reply = _call(
        "POST",
        f"{api}/auth/login",
        form={"username": username, "password": password},
    )
    if reply.status != 200:
        return {}
    return {"Authorization": f"Bearer {reply.json()['access_token']}"}


def _smoke_verify(
    check: Any,
    api: str,
    bearer: dict[str, str],
    day: datetime.date,
    counts: dict[str, Any],
    password: str,
) -> None:
    """Increment 4: verdicts with evidence, the review queue, a review."""
    check(
        "verify: verify run DONE for the date",
        counts["verify_run"] == "DONE",
        str(counts["verify_run"]),
    )
    check(
        "verify: a verdict with evidence for every unique item",
        counts["unique"] > 0
        and counts["verified"] == counts["unique"]
        and counts["with_evidence"] == counts["unique"]
        and counts["verify_failed"] == 0,
        f"{counts['verified']} verdicts ({counts['with_evidence']} with "
        f"evidence, {counts['verify_failed']} failed) for "
        f"{counts['unique']} unique items",
    )
    feed = _call("GET", f"{api}/news?date={day.isoformat()}", bearer)
    if feed.status == 200:
        items = feed.json()["items"]
        verdicts = {i["verdict"] for i in items}
        check(
            "news: every item in the feed has a verdict",
            bool(items) and None not in verdicts,
            ", ".join(sorted(v or "none" for v in verdicts)),
        )
        injected = [
            i for i in items if "INJECTION_ATTEMPT" in i["reason_codes"]
        ]
        check(
            "guard: injection items are flagged and still judged",
            all(i["verdict"] is not None for i in injected),
            f"{len(injected)} flagged: "
            + ", ".join(
                f"{i['vendor_item_id']} {i['verdict']}" for i in injected
            ),
        )
    check(
        "review: a trader can't open the review queue (403)",
        _call("GET", f"{api}/review", bearer).status == 403,
    )
    analyst = _login(api, "analyst1", password)
    check("review: analyst1 logs in", bool(analyst))
    if not analyst:
        return
    queue = _call(
        "GET", f"{api}/review?date={day.isoformat()}&status=PENDING", analyst
    )
    pending = queue.json()["items"] if queue.status == 200 else []
    check(
        "review: low-confidence items wait in the review queue",
        queue.status == 200 and len(pending) == counts["pending"],
        f"HTTP {queue.status}: {len(pending)} in the queue, "
        f"{counts['pending']} pending in the database",
    )
    runs = _call("GET", f"{api}/runs?date={day.isoformat()}", analyst)
    if runs.status == 200 and runs.json()["items"]:
        run_id = runs.json()["items"][0]["run_id"]
        stream = _call(
            "GET", f"{api}/runs/{run_id}/events", analyst, timeout_s=30
        )
        kinds = [name for name, _ in _sse_events(stream.body)]
        check(
            "runs: the event stream replays to run.done",
            stream.status == 200 and kinds[-1:] == ["run.done"],
            f"HTTP {stream.status}: {len(kinds)} events",
        )
    if not pending:
        return
    task = pending[0]
    decided = _call(
        "POST",
        f"{api}/review/{task['id']}",
        analyst,
        body={"action": "approve"},
    )
    check(
        "review: the analyst approves the top item",
        decided.status == 200 and decided.json()["status"] == "APPROVED",
        f"HTTP {decided.status}",
    )
    again = _call(
        "POST",
        f"{api}/review/{task['id']}",
        analyst,
        body={"action": "approve"},
    )
    check("review: a second decision is 409", again.status == 409)
    status = None
    for _ in range(30):
        detail = _call("GET", f"{api}/news/{task['item_id']}", analyst)
        verification = (detail.json() or {}).get("verification") or {}
        status = verification.get("review_status")
        if status == "APPROVED":
            break
        time.sleep(2)
    check(
        "review: the worker resumes the graph (verdict APPROVED)",
        status == "APPROVED",
        f"review_status {status}",
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
        row = conn.execute(
            "SELECT status FROM ai.verify_run WHERE feed_date = %s"
            " ORDER BY requested_at DESC LIMIT 1",
            (day,),
        ).fetchone()
        counts["verify_run"] = None if row is None else row[0]
        row = conn.execute(
            "SELECT count(*) FROM ai.news_item n"
            " JOIN ai.rule_check c ON c.news_id = n.id"
            " LEFT JOIN ai.duplicate_link d ON d.news_id = n.id"
            " WHERE n.feed_date = %s AND d.news_id IS NULL",
            (day,),
        ).fetchone()
        counts["unique"] = row[0]
        row = conn.execute(
            "SELECT count(*) FILTER (WHERE v.verdict IS NOT NULL),"
            " count(*) FILTER (WHERE v.status = 'FAILED'),"
            " count(*) FILTER (WHERE EXISTS (SELECT 1 FROM ai.evidence e"
            "   WHERE e.news_id = v.news_id)),"
            " count(*) FILTER (WHERE v.review_status = 'PENDING')"
            " FROM ai.verification v JOIN ai.news_item n ON n.id = v.news_id"
            " WHERE n.feed_date = %s",
            (day,),
        ).fetchone()
        (
            counts["verified"],
            counts["verify_failed"],
            counts["with_evidence"],
            counts["pending"],
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


def _owner_queue() -> Any:
    from ai_api.worker import queue  # noqa: PLC0415

    host = os.environ.get("REDIS_HOST", "redis")
    password = os.environ.get("REDIS_PASSWORD", "")
    return queue.Queue(queue.make_broker(host, password))


async def _follow(run_id: int, timeout_s: float) -> dict[str, Any]:
    """Prints a run's events until it ends; returns the last event."""
    from redis import asyncio as aioredis  # noqa: PLC0415

    from ai_api.verify import events  # noqa: PLC0415

    redis = aioredis.Redis(
        host=os.environ.get("REDIS_HOST", "redis"),
        password=os.environ.get("REDIS_PASSWORD", ""),
        decode_responses=True,
        socket_timeout=30,
    )
    reader = events.RunEvents(redis)
    after = "0"
    started = time.monotonic()
    last: dict[str, Any] = {}
    try:
        while time.monotonic() - started < timeout_s:
            for event_id, kind, data in await reader.read(run_id, after):
                after = event_id
                last = {"kind": kind, **data}
                if kind == "item":
                    flag = "  -> review" if data.get("review") else ""
                    verdict = data.get("verdict") or "FAILED"
                    print(
                        f"  [{data['done']}/{data['total']}] "
                        f"{data.get('vendor_item_id', data['news_id'])} "
                        f"{verdict}{flag}",
                        flush=True,
                    )
                elif kind == "run.started":
                    print(f"  {data['total']} unique items queued", flush=True)
                if kind in events.FINAL_KINDS:
                    return last
    finally:
        await redis.aclose()
    return {"kind": "timeout"}


def _verify(day: datetime.date, timeout_s: float) -> int:
    """Queues a verify run of ``day`` (as the owner) and follows it."""
    owner = config.Database.from_env(os.environ, "PGUSER", "PGPASSWORD")
    with psycopg.connect(owner.dsn()) as conn:
        statuses = conn.execute(
            "SELECT (SELECT status FROM ai.rule_run WHERE feed_date = %(d)s"
            "        ORDER BY started_at DESC LIMIT 1),"
            "       (SELECT status FROM ai.ai_run WHERE feed_date = %(d)s"
            "        ORDER BY started_at DESC LIMIT 1),"
            "       (SELECT run_id FROM ai.verify_run WHERE feed_date = %(d)s"
            "        AND status IN ('QUEUED', 'RUNNING') LIMIT 1)",
            {"d": day},
        ).fetchone()
        if statuses[0] != "DONE" or statuses[1] != "DONE":
            print(
                f"verify: {day}: rule run {statuses[0] or 'missing'}, AI run "
                f"{statuses[1] or 'missing'}; run `make -C python rules "
                "enrich DATE=...` first",
                file=sys.stderr,
            )
            return 1
        if statuses[2] is not None:
            print(f"verify: run {statuses[2]} of {day} is in progress")
            run_id = statuses[2]
        else:
            run_id = conn.execute(
                "INSERT INTO ai.verify_run (feed_date, requested_by)"
                " VALUES (%s, 'cli') RETURNING run_id",
                (day,),
            ).fetchone()[0]
            conn.commit()

    async def queue_and_follow() -> dict[str, Any]:
        if statuses[2] is None:
            jobs = _owner_queue()
            await jobs.start()
            try:
                await jobs.run_day(run_id)
            finally:
                await jobs.stop()
            print(f"verify {day}: run {run_id} queued", flush=True)
        return await _follow(run_id, timeout_s)

    last = asyncio.run(queue_and_follow())
    if last.get("kind") != "run.done":
        print(f"verify {day}: run {run_id} {last}", file=sys.stderr)
        return 1
    print(
        f"verify {day}: {last['done']} verified -> {last['verified']} VERIFIED,"
        f" {last['unverified']} UNVERIFIED, {last['misleading']} MISLEADING,"
        f" {last['fake']} FAKE; {last['pending_review']} to review,"
        f" {last['escalated']} escalated, {last['failed']} failed"
        f" ({last['total_ms']} ms)"
    )
    return 1 if last["failed"] else 0


def _expire(day: datetime.date) -> int:
    """Market open: the day's pending reviews expire (the graphs resume)."""
    from ai_api import verdicts  # noqa: PLC0415

    owner = config.Database.from_env(os.environ, "PGUSER", "PGPASSWORD")
    with psycopg.connect(owner.dsn()) as conn:
        expired = verdicts.expire_pending(conn, day)
        conn.commit()

    async def resume_all() -> None:
        jobs = _owner_queue()
        await jobs.start()
        try:
            for task in expired:
                await jobs.resume(
                    task["run_id"],
                    task["news_id"],
                    task["thread_id"],
                    {"action": "expire"},
                )
        finally:
            await jobs.stop()

    if expired:
        asyncio.run(resume_all())
    print(f"expire {day}: {len(expired)} pending reviews expired")
    return 0


def _ml_train() -> int:
    from ai_api.ml import train  # noqa: PLC0415

    model_dir = pathlib.Path(os.environ.get("ML_MODEL_DIR", "/models"))
    info = train.train(model_dir)
    print(json.dumps(info, indent=2))
    return 0


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
            "verify",
            "expire",
            "ml-train",
            "smoke",
        ),
    )
    parser.add_argument("--base-url", default="http://edge:8080")
    parser.add_argument(
        "--date", type=datetime.date.fromisoformat, default=None
    )
    parser.add_argument(
        "--timeout", type=float, default=7200, help="verify: seconds"
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
        if args.command == "ml-train":
            return _ml_train()
        day = args.date
        if day is None:
            day = datetime.datetime.now(_NEW_YORK).date()
        if args.command == "rules":
            return _rules(day)
        if args.command == "dedup-rebuild":
            return _dedup_rebuild(day)
        if args.command == "enrich":
            return _enrich(day)
        if args.command == "verify":
            return _verify(day, args.timeout)
        if args.command == "expire":
            return _expire(day)
        return _smoke(args.base_url, day)
    except (config.ConfigError, fastpath.FastpathMissingError) as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
