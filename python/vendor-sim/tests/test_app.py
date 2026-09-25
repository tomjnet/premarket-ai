import json

from fastapi.testclient import TestClient

from vendor_sim import app as app_module


def test_health():
    client = TestClient(app_module.app)
    assert client.get("/health").json()["status"] == "ok"


def test_feed_serves_items_without_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", str(tmp_path))
    client = TestClient(app_module.app)
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
    client = TestClient(app_module.app)
    assert client.get("/feed", params={"date": "not-a-date"}).status_code == 422


def test_health_command_fails_when_nothing_listens(monkeypatch):
    from vendor_sim import cli

    monkeypatch.setenv("HEALTH_URL", "http://127.0.0.1:9/health")
    assert cli.main(["health"]) == 1
