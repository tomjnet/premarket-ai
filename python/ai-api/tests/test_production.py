"""Increment 6: alerts, the budget banner, metrics, retention, pgvector."""

from __future__ import annotations

import asyncio
import datetime
import uuid

import conftest
import fakeredis
from fastapi import testclient
from langchain_core import messages
from langchain_core import outputs
from opentelemetry import metrics
from opentelemetry.sdk import metrics as sdk_metrics
from opentelemetry.sdk.metrics import export
import pytest

from ai_api import alerts
from ai_api import app
from ai_api import deps
from ai_api import retention
from ai_api import sessions
from ai_api import telemetry
from ai_api.llm import budget
from ai_api.rag import config as rag_config
from ai_api.rag import store
from ai_api.routes import alerts as alert_routes

TOKEN = "w" * 40


def run(coro):
    return asyncio.run(coro)


# --- the alerts stream --------------------------------------------------------


def test_publish_dedups_and_resolve_clears():
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    stream = alerts.Alerts(redis)
    alert = alerts.Alert(key="sla:verify:2026-09-28", title="late")
    assert run(stream.publish(alert)) is not None
    assert run(stream.publish(alert)) is None
    assert run(stream.resolve("sla:brief:2026-09-28", "ok", "test")) is None
    assert run(stream.resolve(alert.key, "done", "scheduler")) is not None
    events = run(stream.read(block_ms=0))
    assert [e["status"] for _, e in events] == ["firing", "resolved"]
    assert alerts.active(events) == []
    run(stream.publish(alert))
    assert [a["key"] for a in alerts.active(run(stream.since()))] == [alert.key]


def test_alert_fields_are_checked():
    with pytest.raises(ValueError):
        alerts.Alert(key="k", title="t", severity="page")
    with pytest.raises(ValueError):
        alerts.Alert(key="", title="t")
    data = alerts.Alert(key="k", title="t").to_json()
    assert data["at"].endswith("Z")
    assert data["source"] == "scheduler"


# --- the API ------------------------------------------------------------------


class AlertHarness:
    """The app with Redis alerts and the budget, as in production."""

    def __init__(self, token: str = TOKEN) -> None:
        """Wires the fakes."""
        settings = conftest.make_settings(
            alert_webhook_token=token, monthly_budget_usd=20.0
        )
        self.redis = fakeredis.FakeAsyncRedis(decode_responses=True)
        self.users = conftest.FakeUsers()
        services = deps.Services(
            settings=settings,
            users=self.users,
            news=conftest.FakeNews(),
            sessions=sessions.SessionStore(
                self.redis,
                ttl_s=3600,
                grace_s=30,
                max_failures=5,
                lockout_s=900,
            ),
            ping=conftest._ping,
            alerts=alerts.Alerts(self.redis),
            budget=budget.CloudBudget(self.redis, 20.0),
        )
        self.client = testclient.TestClient(
            app.create_app(services=services), base_url="https://testserver"
        )

    def bearer(self, username: str) -> dict[str, str]:
        """Logs in; returns the Authorization header."""
        response = self.client.post(
            "/auth/login",
            data={"username": username, "password": conftest.PASSWORD},
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}


_PAYLOAD = {
    "receiver": "premarket-banner",
    "status": "firing",
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "WorkerDown", "severity": "critical"},
            "annotations": {"summary": "No verification worker is running"},
            "fingerprint": "abc123",
        }
    ],
}


def test_grafana_webhook_needs_its_token():
    h = AlertHarness()
    with h.client:
        url = "/alerts/grafana"
        assert h.client.post(url, json=_PAYLOAD).status_code == 401
        wrong = {"Authorization": "Bearer " + "x" * 40}
        assert (
            h.client.post(url, json=_PAYLOAD, headers=wrong).status_code == 401
        )
        ok = {"Authorization": f"Bearer {TOKEN}"}
        assert h.client.post(url, json=_PAYLOAD, headers=ok).status_code == 204
        # Grafana repeats a firing alert: the banner gets it once.
        assert h.client.post(url, json=_PAYLOAD, headers=ok).status_code == 204
        analyst = h.bearer("analyst1")
        found = h.client.get("/alerts", headers=analyst).json()
        assert found["count"] == 1
        item = found["items"][0]
        assert item["key"] == "grafana:WorkerDown:abc123"
        assert item["severity"] == "critical"
        assert item["source"] == "grafana"
        resolved = dict(_PAYLOAD)
        resolved["alerts"] = [dict(_PAYLOAD["alerts"][0], status="resolved")]
        h.client.post(url, json=resolved, headers=ok)
        assert h.client.get("/alerts", headers=analyst).json()["count"] == 0


def test_webhook_off_without_a_token():
    h = AlertHarness(token="")
    with h.client:
        response = h.client.post(
            "/alerts/grafana",
            json=_PAYLOAD,
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert response.status_code == 404


def test_alerts_are_for_analysts_and_admins():
    h = AlertHarness()
    with h.client:
        assert h.client.get("/alerts").status_code == 401
        trader = h.bearer("trader1")
        assert h.client.get("/alerts", headers=trader).status_code == 403
        assert h.client.get("/alerts/stream", headers=trader).status_code == 403
        admin = h.bearer("admin1")
        assert h.client.get("/alerts", headers=admin).status_code == 200


def test_alert_stream_starts_with_a_snapshot(monkeypatch):
    # The stream ends right after the snapshot (it tails for an hour).
    monkeypatch.setattr(alert_routes, "_STREAM_MAX_S", 0)
    h = AlertHarness()
    run(
        alerts.Alerts(h.redis).publish(
            alerts.Alert(key="sla:brief:2026-09-28", title="Brief late")
        )
    )
    with h.client:
        admin = h.bearer("admin1")
        response = h.client.get("/alerts/stream", headers=admin)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    lines = response.text.splitlines()
    assert lines[1] == "event: snapshot"
    assert '"sla:brief:2026-09-28"' in lines[2]


def test_budget_banner_for_every_role():
    h = AlertHarness()
    with h.client:
        trader = h.bearer("trader1")
        body = h.client.get("/llm/budget", headers=trader).json()
        assert body == {
            "spent_usd": 0.0,
            "cap_usd": 20.0,
            "share": 0.0,
            "warning": False,
            "reached": False,
        }
        run(budget.CloudBudget(h.redis, 20.0).add(20.5))
        body = h.client.get("/llm/budget", headers=trader).json()
        assert body["reached"]
        assert body["warning"]


def test_budget_alerts_at_80_and_100_percent_once():
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    cap = budget.CloudBudget(redis, 10.0)
    run(cap.add(5.0))
    run(cap.add(3.5))  # 85%: crosses 80%
    run(cap.add(0.5))  # 90%: no new alert
    run(cap.add(2.0))  # 110%: crosses the cap
    run(cap.add(1.0))
    events = run(alerts.Alerts(redis).read(block_ms=0))
    keys = [data["key"].split(":")[1] for _, data in events]
    assert keys == ["80", "100"]
    assert events[1][1]["severity"] == "critical"
    today = datetime.datetime.now(datetime.UTC).date()
    assert run(cap.spent_on(today)) == pytest.approx(12.0)


# --- GenAI metrics ------------------------------------------------------------


@pytest.fixture(scope="module")
def reader():
    found = export.InMemoryMetricReader()
    metrics.set_meter_provider(sdk_metrics.MeterProvider([found]))
    yield found


def _points(reader, name):
    data = reader.get_metrics_data()
    for resource in data.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                if metric.name == name:
                    return list(metric.data.data_points)
    return []


def test_genai_metrics_follow_the_semantic_conventions(reader):
    telemetry.reset()
    handler = telemetry.GenAiMetrics("main-gpu4gb")
    call = uuid.uuid4()
    handler.on_chat_model_start({}, [[]], run_id=call)
    answer = messages.AIMessage(
        "ok",
        usage_metadata={
            "input_tokens": 120,
            "output_tokens": 30,
            "total_tokens": 150,
        },
    )
    handler.on_llm_end(
        outputs.LLMResult(
            generations=[[outputs.ChatGeneration(message=answer)]]
        ),
        run_id=call,
    )
    failed = uuid.uuid4()
    handler.on_chat_model_start({}, [[]], run_id=failed)
    handler.on_llm_error(TimeoutError("slow"), run_id=failed)
    durations = _points(reader, "gen_ai.client.operation.duration")
    attributes = [dict(p.attributes) for p in durations]
    assert {
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": "litellm",
        "gen_ai.request.model": "main-gpu4gb",
    } in attributes
    assert any(a.get("error.type") == "TimeoutError" for a in attributes)
    tokens = {
        p.attributes["gen_ai.token.type"]: p.sum
        for p in _points(reader, "gen_ai.client.token.usage")
    }
    assert tokens == {"input": 120, "output": 30}


def test_worker_and_http_metrics(reader):
    telemetry.reset()
    telemetry.worker_started()
    telemetry.verify_item("done")
    telemetry.record_http("/news/{item_id}", "GET", 200, 0.05)
    assert _points(reader, "premarket.worker.starts")[0].value == 1
    assert _points(reader, "premarket.worker.up")[0].value == 1
    assert _points(reader, "premarket.verify.items")[0].attributes == {
        "outcome": "done"
    }
    route = _points(reader, "http.server.request.duration")[0].attributes
    assert route["http.route"] == "/news/{item_id}"


def test_setup_without_an_endpoint_exports_nothing():
    assert not telemetry.setup("ai-api", {})


# --- retention, pgvector helpers ----------------------------------------------


def test_retention_cutoff():
    today = datetime.date(2026, 12, 31)
    assert retention.cutoff_for(today, 90) == datetime.date(2026, 10, 2)
    with pytest.raises(ValueError):
        retention.cutoff_for(today, 0)


def test_vector_store_settings():
    cfg = rag_config.RagConfig.from_env({"VECTOR_STORE": "pgvector"})
    assert cfg.vector_store == "pgvector"
    assert cfg.hybrid
    cfg = rag_config.RagConfig.from_env(
        {"VECTOR_STORE": "pgvector", "RAG_HYBRID": "false"}
    )
    assert not cfg.hybrid
    with pytest.raises(ValueError):
        rag_config.RagConfig.from_env({"VECTOR_STORE": "faiss"})
    with pytest.raises(ValueError):
        rag_config.RagConfig.from_env({"RAG_HYBRID": "maybe"})


def test_pgvector_helpers():
    assert store.vector_literal([0.5, 1, -2.25]) == "[0.5,1.0,-2.25]"
    assert store._dims_of("vector(768)") == 768
    assert store._dims_of("vector") is None
    cfg = rag_config.RagConfig(vector_store="pgvector")
    with pytest.raises(ValueError):
        store.open_store(cfg, None, "embed-gpu4gb", 768)
    vectors = store.ChunkVectors(None, None, "embed-gpu4gb")
    with pytest.raises(ValueError):
        run(vectors.aadd_texts(["a", "b"], ids=["1"]))
    with pytest.raises(NotImplementedError):
        vectors.similarity_search("q")
