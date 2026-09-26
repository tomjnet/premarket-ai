"""``POST /chat``: SSE stream, roles, the per-user gate, chat turned off."""

import asyncio
import dataclasses
import json

import conftest
from fastapi import testclient

from ai_api import app
from ai_api import deps
from ai_api.rag import ask
from ai_api.routes import chat


class _FakeAsk:
    def __init__(self):
        self.questions = []

    async def stream(self, question, day, user):
        self.questions.append((question, day, user))
        yield ask.Event("sources", {"sources": [], "reranked": True})
        yield ask.Event("token", {"text": "Rates held "})
        yield ask.Event("token", {"text": "[1]."})
        yield ask.Event("done", {"answer": "Rates held [1].", "citations": [1]})


def _events(text):
    found = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        found.append((lines["event"], json.loads(lines["data"])))
    return found


def _client(harness, ask_service):
    services = deps.Services(
        settings=harness.settings,
        users=harness.users,
        news=harness.news,
        sessions=harness.sessions,
        ping=conftest._ping,
        ask=ask_service,
        chat_gate=chat.ChatGate(harness.redis),
    )
    return testclient.TestClient(
        app.create_app(services=services), base_url="https://testserver"
    )


def test_chat_streams_events(harness):
    fake = _FakeAsk()
    token = harness.login()
    with _client(harness, fake) as client:
        response = client.post(
            "/chat",
            json={"question": "What did the Fed do?", "date": "2026-09-24"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    names = [name for name, _ in _events(response.text)]
    assert names == ["sources", "token", "token", "done"]
    assert fake.questions[0][2] == "trader1"
    assert ("chat", "trader1") in harness.users.events
    # The gate is free again after the answer.
    assert asyncio.run(harness.redis.get("chat:busy:trader1")) is None


def test_chat_needs_a_login_and_a_valid_question(harness):
    with _client(harness, _FakeAsk()) as client:
        assert client.post("/chat", json={"question": "hi?"}).status_code == 401
        token = harness.login()
        bearer = {"Authorization": f"Bearer {token}"}
        assert (
            client.post("/chat", json={"question": "x"}, headers=bearer)
        ).status_code == 422
        assert (
            client.post(
                "/chat",
                json={"question": "hello there", "extra": 1},
                headers=bearer,
            )
        ).status_code == 422


def test_one_question_at_a_time_per_user(harness):
    token = harness.login()
    asyncio.run(harness.redis.set("chat:busy:trader1", "1"))
    with _client(harness, _FakeAsk()) as client:
        response = client.post(
            "/chat",
            json={"question": "What did the Fed do?"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 429


def test_chat_is_503_when_the_llm_is_not_configured(harness):
    token = harness.login()
    with _client(harness, None) as client:
        response = client.post(
            "/chat",
            json={"question": "What did the Fed do?"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 503


def test_a_failing_answer_ends_with_an_error_event(harness):
    class _Broken:
        async def stream(self, question, day, user):
            del question, day, user
            yield ask.Event("sources", {"sources": []})
            raise RuntimeError("gateway down")

    token = harness.login()
    with _client(harness, _Broken()) as client:
        response = client.post(
            "/chat",
            json={"question": "What did the Fed do?"},
            headers={"Authorization": f"Bearer {token}"},
        )
    names = [name for name, _ in _events(response.text)]
    assert names == ["sources", "error"]
    assert asyncio.run(harness.redis.get("chat:busy:trader1")) is None


def test_services_default_to_no_chat(harness):
    fields = {f.name: f.default for f in dataclasses.fields(deps.Services)}
    assert fields["ask"] is None and fields["chat_gate"] is None
