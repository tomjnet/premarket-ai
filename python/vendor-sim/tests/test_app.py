"""Tests for the vendor-sim HTTP API and its health command."""

import json

from fastapi import testclient

from vendor_sim import app
from vendor_sim import cli


def test_health():
    client = testclient.TestClient(app.app)
    assert client.get("/health").json()["status"] == "ok"


def test_feed_serves_items_without_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "_DATA_DIR", str(tmp_path))
    client = testclient.TestClient(app.app)
    body = client.get("/feed", params={"date": "2026-09-24"}).json()

    assert body["feed_date"] == "2026-09-24"
    assert body["count"] == 100
    item = body["items"][0]
    assert set(item) == {
        "id",
        "headline",
        "body",
        "source_url",
        "source_domain",
        "published_at",
        "tickers",
        "synthetic",
    }
    assert item["published_at"].endswith("Z")

    labels = (tmp_path / "2026-09-24" / "labels.jsonl").read_text().splitlines()
    assert len(labels) == 100
    assert "expected_verdict" in json.loads(labels[0])


def test_bad_date_is_rejected():
    client = testclient.TestClient(app.app)
    assert client.get("/feed", params={"date": "not-a-date"}).status_code == 422


def test_health_command_fails_when_nothing_listens(monkeypatch):
    monkeypatch.setenv("HEALTH_URL", "http://127.0.0.1:9/health")
    assert cli.main(["health"]) == 1
