"""The news endpoints: contract shape, filters, errors and roles."""

import datetime
import re

import jwt

from ai_api import config
from ai_api import news
from ai_api import tokens

_UTC_Z = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


def _bearer(harness) -> dict[str, str]:
    return {"Authorization": f"Bearer {harness.login()}"}


def test_news_requires_a_token(harness):
    response = harness.client.get("/news")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "Not authenticated"}


def test_forged_token_is_rejected(harness):
    forged = jwt.encode(
        {"sub": "admin1", "role": "ADMIN", "sid": "x"},
        "not-the-secret",
        algorithm="HS256",
    )
    none_alg = jwt.encode(
        {"sub": "admin1", "role": "ADMIN"}, key=None, algorithm="none"
    )
    for token in (forged, none_alg, "garbage"):
        response = harness.client.get(
            "/news", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 401


def test_expired_token_is_rejected(harness):
    harness.login()
    sid = harness.session_ids()[0]
    token = tokens.issue(
        tokens.Claims("trader1", "TRADER", sid),
        harness.settings.jwt_secret,
        60,
        now=0,
    )
    response = harness.client.get(
        "/news", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_feed_matches_the_contract(harness):
    response = harness.client.get(
        "/news", params={"date": "2026-09-24"}, headers=_bearer(harness)
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "date",
        "run",
        "rule_run",
        "ai_run",
        "count",
        "items",
    }
    assert body["date"] == "2026-09-24"
    assert body["count"] == len(body["items"]) == 2
    assert body["run"] == {
        "run_id": 42,
        "status": "DONE",
        "started_at": "2026-09-24T09:30:02Z",
        "finished_at": "2026-09-24T09:30:05Z",
        "rows_received": 3,
        "dups": 1,
    }
    assert body["rule_run"] == {
        "status": "DONE",
        "finished_at": "2026-09-24T10:00:00Z",
        "items": 3,
        "duplicates": 1,
        "flagged": 1,
    }
    assert body["ai_run"] == {
        "status": "DONE",
        "finished_at": "2026-09-24T10:09:00Z",
        "items": 2,
        "paraphrases": 0,
        "conflicts": 0,
        "summarized": 2,
        "fallbacks": 0,
        "failed": 0,
        "model": "main-gpu4gb",
    }
    item = body["items"][0]
    assert set(item) == {
        "id",
        "vendor_item_id",
        "feed_date",
        "headline",
        "excerpt",
        "source_url",
        "source_domain",
        "published_at",
        "tickers",
        "synthetic",
        "is_dup",
        "dup_of",
        "reason_codes",
        "dup_type",
        "copies",
        "rules_checked",
        "summary",
        "sentiment",
    }
    assert _UTC_Z.match(item["published_at"])
    assert "body" not in item
    assert "rule_evidence" not in item
    by_id = {entry["id"]: entry for entry in body["items"]}
    assert by_id[2001]["copies"] == 1
    assert by_id[2002]["reason_codes"] == ["FAKE_COMPANY", "FAKE_TICKER"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_filters_are_passed_through(harness):
    response = harness.client.get(
        "/news",
        params={
            "date": "2026-09-24",
            "ticker": "msft",
            "q": "  earnings  ",
            "include_duplicates": "true",
        },
        headers=_bearer(harness),
    )

    assert response.status_code == 200
    assert harness.news.queries[-1] == news.NewsQuery(
        day=datetime.date(2026, 9, 24),
        ticker="MSFT",
        text="earnings",
        include_duplicates=True,
    )


def test_blank_search_means_no_search(harness):
    harness.client.get(
        "/news",
        params={"date": "2026-09-24", "q": "   "},
        headers=_bearer(harness),
    )
    assert harness.news.queries[-1].text is None


def test_no_run_for_the_date(harness):
    body = harness.client.get(
        "/news", params={"date": "2026-09-26"}, headers=_bearer(harness)
    ).json()
    assert body == {
        "date": "2026-09-26",
        "run": None,
        "rule_run": None,
        "ai_run": None,
        "count": 0,
        "items": [],
    }


def test_duplicates_carry_the_match_type(harness):
    body = harness.client.get(
        "/news",
        params={"date": "2026-09-24", "include_duplicates": "true"},
        headers=_bearer(harness),
    ).json()
    duplicate = next(item for item in body["items"] if item["is_dup"])
    assert duplicate["dup_of"] == "VND-20260924-001"
    assert duplicate["dup_type"] == "near"


def test_items_before_the_rule_run_keep_the_legacy_flags(harness):
    harness.news.rows[0].update(rules_checked=False, evidence=None)
    harness.news.rule_run = None
    body = harness.client.get(
        "/news", params={"date": "2026-09-24"}, headers=_bearer(harness)
    ).json()
    assert body["rule_run"] is None
    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[2001]["rules_checked"] is False
    detail = harness.client.get("/news/2001", headers=_bearer(harness))
    assert detail.json()["rule_evidence"] == []


def test_running_run_has_null_finished_at(harness):
    harness.news.run = dict(
        harness.news.run, status="RUNNING", finished_at=None
    )
    body = harness.client.get(
        "/news", params={"date": "2026-09-24"}, headers=_bearer(harness)
    ).json()
    assert body["run"]["finished_at"] is None


def test_bad_parameters_are_422(harness):
    bearer = _bearer(harness)
    for params in (
        {"date": "2026-02-30"},
        {"ticker": "AAPL;DROP"},
        {"q": "x" * 201},
        {"include_duplicates": "maybe"},
    ):
        response = harness.client.get("/news", params=params, headers=bearer)
        assert response.status_code == 422, params


def test_detail_has_the_body_and_rule_evidence(harness):
    response = harness.client.get("/news/2001", headers=_bearer(harness))
    assert response.status_code == 200
    assert response.json()["body"].startswith("NEW YORK")
    assert response.json()["rule_evidence"] == [
        {
            "check": "entity",
            "code": None,
            "message": "AAPL is Apple Inc. in the SEC ticker registry.",
        }
    ]


def test_detail_404_and_bad_id(harness):
    bearer = _bearer(harness)
    missing = harness.client.get("/news/99999", headers=bearer)
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Not found"}
    assert harness.client.get("/news/0", headers=bearer).status_code == 422
    assert harness.client.get("/news/abc", headers=bearer).status_code == 422


def test_untrusted_text_is_returned_as_plain_json(harness):
    harness.news.rows[0]["headline"] = "<script>alert(1)</script>"
    response = harness.client.get("/news/2001", headers=_bearer(harness))
    assert response.headers["content-type"] == "application/json"
    assert response.json()["headline"] == "<script>alert(1)</script>"


def test_excerpt_is_one_line_and_at_most_280_characters():
    body = "Line one.\n\n" + "é" * 400
    text = news.excerpt(body)
    assert "\n" not in text
    assert len(text) == 280
    assert text.endswith("…")
    assert news.excerpt("  short\tbody ") == "short body"


def test_like_pattern_escapes_wildcards():
    assert news.like_pattern("50%_off\\") == "%50\\%\\_off\\\\%"


def test_health(harness):
    assert harness.client.get("/health").json() == {"status": "ok"}


def test_docs_are_off_by_default(harness):
    assert harness.client.get("/docs").status_code == 404
    assert harness.client.get("/openapi.json").status_code == 404


def test_unknown_role_in_a_signed_token_is_rejected():
    token = tokens.issue(tokens.Claims("x", "ROOT", "sid"), "k" * 40, 60)
    try:
        tokens.verify(token, "k" * 40)
    except tokens.InvalidTokenError:
        return
    raise AssertionError("ROOT accepted")


def test_settings_reject_placeholder_secrets():
    env = {
        "AI_DB_USER": "premarket_ai",
        "AI_DB_PASSWORD": "p" * 40,
        "REDIS_PASSWORD": "r" * 40,
        "JWT_SECRET": "change-me",
    }
    try:
        config.Settings.from_env(env)
    except config.ConfigError as e:
        assert "JWT_SECRET" in str(e)
        return
    raise AssertionError("placeholder accepted")


def test_detail_has_the_ai_results(harness):
    body = harness.client.get("/news/2001", headers=_bearer(harness)).json()
    assert body["summary"] == "Apple said item 1 happened."
    assert body["sentiment"] == "neutral"
    assert body["ai"] == {
        "status": "DONE",
        "model": "main-gpu4gb",
        "prompt_version": "enrich-v1",
        "enriched_at": "2026-09-24T10:05:00Z",
        "summary_source": "llm",
        "companies": [{"name": "Apple Inc.", "ticker": "AAPL"}],
        "claims": ["Apple said X."],
        "evidence": [],
    }


def test_detail_before_the_ai_run_has_no_ai(harness):
    harness.news.rows[1].update(
        ai_status=None, summary=None, sentiment=None, summary_source=None
    )
    body = harness.client.get("/news/2002", headers=_bearer(harness)).json()
    assert body["ai"] is None
    assert body["summary"] is None
