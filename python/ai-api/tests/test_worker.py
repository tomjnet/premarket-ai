"""The worker's broker factory: settings, and the three tasks registered."""

import pytest

from ai_api import config
from ai_api.worker import app
from ai_api.worker import queue

_ENV = {
    "WORKER_DB_USER": "premarket_worker",
    "WORKER_DB_PASSWORD": "w" * 40,
    "REDIS_PASSWORD": "r" * 40,
    "LLM_GATEWAY_KEY": "k" * 40,
    "MCP_SERVICE_TOKEN": "t" * 40,
}


def test_the_broker_registers_every_task(monkeypatch):
    for name, value in _ENV.items():
        monkeypatch.setenv(name, value)
    broker = app.build_broker()
    for task in (queue.RUN_DAY, queue.VERIFY_ITEM, queue.RESUME):
        assert broker.find_task(task) is not None, task


def test_verify_settings():
    settings = config.VerifySettings.from_env(
        {**_ENV, "HITL_CONFIDENCE_MIN": "0.8", "JUDGE_CLOUD_MODEL": "cloud-x"}
    )
    assert settings.hitl_confidence_min == 0.8
    assert settings.judge_cloud_model == "cloud-x"
    assert settings.llama_guard and settings.ml_enabled
    assert settings.database.user == "premarket_worker"
    with pytest.raises(config.ConfigError):
        config.VerifySettings.from_env({**_ENV, "HITL_CONFIDENCE_MIN": "7"})
    with pytest.raises(config.ConfigError):
        config.VerifySettings.from_env({**_ENV, "MCP_SERVICE_TOKEN": "short"})


def test_redis_url_quotes_the_password():
    assert (
        queue.redis_url("redis", "a/b@c") == "redis://:a%2Fb%40c@redis:6379/0"
    )
