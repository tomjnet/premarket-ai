"""ai-api command line.

Usage:

    ai-api init                       migrations, DB role, demo users
    ai-api health                     exit 0 if the API answers /health
    ai-api openapi                    the OpenAPI document on stdout
    ai-api rules --date YYYY-MM-DD    rule checks of a feed date (no LLM)
    ai-api registry                   refresh the SEC ticker registry now
    ai-api dedup-rebuild --date YYYY-MM-DD
                                      re-index the 7-day dedup window
    ai-api smoke --base-url URL --date YYYY-MM-DD
                                      the increment's "done when" check

``init``, ``rules``, ``registry``, ``dedup-rebuild`` and ``smoke`` run as
the database owner, in the one-shot ``ai-api-init`` container.
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
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import zoneinfo

import psycopg

from ai_api import app
from ai_api import bootstrap
from ai_api import config
from ai_api.dedup import fastpath
from ai_api.rules import runner

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
) -> _Reply:
    data = None
    all_headers = {} if headers is None else dict(headers)
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        all_headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(
        url, data=data, headers=all_headers, method=method
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=10) as response:
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
    settings = config.RulesSettings.from_env(os.environ)
    try:
        asyncio.run(runner.run(settings, day))
    except runner.NotReadyError as e:
        print(f"rules: {e}", file=sys.stderr)
        return 1
    return 0


def _registry() -> int:
    settings = config.RulesSettings.from_env(os.environ)
    tickers = asyncio.run(runner.refresh_registry(settings))
    print(f"SEC ticker registry: {tickers} tickers")
    return 0 if tickers else 1


def _dedup_rebuild(day: datetime.date) -> int:
    settings = config.RulesSettings.from_env(os.environ)
    indexed = asyncio.run(runner.rebuild_index(settings, day))
    print(f"dedup index: {indexed} unique items re-indexed")
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
            bootstrap.run(os.environ)
            return 0
        if args.command == "registry":
            return _registry()
        day = args.date
        if day is None:
            day = datetime.datetime.now(_NEW_YORK).date()
        if args.command == "rules":
            return _rules(day)
        if args.command == "dedup-rebuild":
            return _dedup_rebuild(day)
        return _smoke(args.base_url, day)
    except (config.ConfigError, fastpath.FastpathMissingError) as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
