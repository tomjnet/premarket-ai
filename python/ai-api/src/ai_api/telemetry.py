"""OpenTelemetry metrics (increment 6): GenAI calls, the API, the worker.

With ``OTEL_EXPORTER_OTLP_ENDPOINT`` set (the ``observability`` profile:
``http://otel-collector:4318``), ``setup`` installs a meter provider that
pushes every 15 s over OTLP/HTTP to the OpenTelemetry Collector, which
Prometheus scrapes. Without it, every instrument is OpenTelemetry's no-op
and costs nothing.

Metrics (OpenTelemetry names; Prometheus replaces dots with underscores and
adds the unit):

- ``gen_ai.client.operation.duration`` (s, histogram) and
  ``gen_ai.client.token.usage`` (histogram, ``gen_ai.token.type`` input or
  output): the GenAI semantic conventions, one point per chat call, with
  ``gen_ai.operation.name`` = ``chat``, ``gen_ai.request.model`` = the
  gateway alias (``main-gpu4gb``, ``cloud-openai``...) and
  ``gen_ai.provider.name`` = ``litellm`` (every call goes through the
  gateway). ``error.type`` is set on a failed call.
- ``http.server.request.duration`` (s): ai-api requests by route template
  and status code.
- ``premarket.worker.up`` (gauge, 1 per live worker process) and
  ``premarket.worker.starts`` (counter): Grafana alerts when no worker is
  up or one restarts in a loop.
- ``premarket.verify.items`` (counter by outcome: done, review, skipped,
  failed).
"""

from __future__ import annotations

from collections.abc import Mapping
import functools
import logging
import time
from typing import Any
import uuid

from langchain_core import callbacks
from langchain_core import outputs
from opentelemetry import metrics

_log = logging.getLogger(__name__)
_METER = "premarket-ai"
_EXPORT_INTERVAL_MS = 15_000
_PROVIDER = "litellm"
# Buckets of the GenAI semantic conventions (seconds, tokens).
_DURATION_BUCKETS = (
    0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28, 2.56, 5.12, 10.24,
    20.48, 40.96, 81.92,
)  # fmt: skip
_TOKEN_BUCKETS = (
    1, 4, 16, 64, 256, 1024, 4096, 16384, 65536, 262144, 1048576,
)  # fmt: skip


def setup(service: str, env: Mapping[str, str]) -> bool:
    """Installs the OTLP meter provider when an endpoint is configured.

    Args:
        service: ``service.name`` (``ai-api``, ``ai-worker``...).
        env: The environment (OTEL_EXPORTER_OTLP_ENDPOINT).

    Returns:
        True when metrics are exported.
    """
    endpoint = env.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip().rstrip("/")
    if not endpoint:
        return False
    # Imported here: only processes that export pay for the SDK import.
    from opentelemetry.exporter.otlp.proto.http import (  # noqa: PLC0415
        metric_exporter,
    )
    from opentelemetry.sdk import metrics as sdk_metrics  # noqa: PLC0415
    from opentelemetry.sdk import resources  # noqa: PLC0415
    from opentelemetry.sdk.metrics import export  # noqa: PLC0415
    from opentelemetry.sdk.metrics import view  # noqa: PLC0415

    reader = export.PeriodicExportingMetricReader(
        metric_exporter.OTLPMetricExporter(
            endpoint=f"{endpoint}/v1/metrics", timeout=5
        ),
        export_interval_millis=_EXPORT_INTERVAL_MS,
    )
    views = [
        view.View(
            instrument_name="gen_ai.client.operation.duration",
            aggregation=view.ExplicitBucketHistogramAggregation(
                _DURATION_BUCKETS
            ),
        ),
        view.View(
            instrument_name="gen_ai.client.token.usage",
            aggregation=view.ExplicitBucketHistogramAggregation(_TOKEN_BUCKETS),
        ),
    ]
    provider = sdk_metrics.MeterProvider(
        metric_readers=[reader],
        resource=resources.Resource.create(
            {
                "service.name": service,
                "service.namespace": "premarket-ai",
                "service.instance.id": uuid.uuid4().hex[:12],
            }
        ),
        views=views,
    )
    metrics.set_meter_provider(provider)
    _log.info("metrics: OTLP to %s every %d s", endpoint, 15)
    return True


def shutdown() -> None:
    """Flushes the last metrics (short-lived commands)."""
    provider = metrics.get_meter_provider()
    stop = getattr(provider, "shutdown", None)
    if stop is not None:
        stop()


@functools.cache
def _instruments() -> dict[str, Any]:
    """The instruments, created once on the installed provider."""
    meter = metrics.get_meter(_METER)
    return {
        "duration": meter.create_histogram(
            "gen_ai.client.operation.duration",
            unit="s",
            description="GenAI operation duration.",
        ),
        "tokens": meter.create_histogram(
            "gen_ai.client.token.usage",
            unit="{token}",
            description="Input and output tokens used.",
        ),
        "http": meter.create_histogram(
            "http.server.request.duration",
            unit="s",
            description="Duration of HTTP server requests.",
        ),
        "worker_starts": meter.create_counter(
            "premarket.worker.starts",
            description="Worker process starts (a loop means crashes).",
        ),
        "verify_items": meter.create_counter(
            "premarket.verify.items",
            description="Items the verify graph finished, by outcome.",
        ),
    }


def reset() -> None:
    """Forgets the instruments (tests install their own provider)."""
    _instruments.cache_clear()


def record_http(route: str, method: str, status: int, seconds: float) -> None:
    """One API request."""
    _instruments()["http"].record(
        seconds,
        {
            "http.route": route,
            "http.request.method": method,
            "http.response.status_code": status,
        },
    )


def worker_started() -> None:
    """Counts a worker start and reports it as up while it lives."""
    _instruments()["worker_starts"].add(1)
    metrics.get_meter(_METER).create_observable_gauge(
        "premarket.worker.up",
        callbacks=[lambda _options: [metrics.Observation(1)]],
        description="1 per live verification worker process.",
    )


def verify_item(outcome: str) -> None:
    """One item job the worker finished (done, review, skipped, failed)."""
    _instruments()["verify_items"].add(1, {"outcome": outcome})


def _usage(response: outputs.LLMResult) -> tuple[int | None, int | None]:
    """(input, output) tokens of a chat answer, when the model reports them."""
    for generations in response.generations:
        for generation in generations:
            message = getattr(generation, "message", None)
            usage = getattr(message, "usage_metadata", None)
            if usage:
                return usage.get("input_tokens"), usage.get("output_tokens")
    token_usage = (response.llm_output or {}).get("token_usage") or {}
    return token_usage.get("prompt_tokens"), token_usage.get(
        "completion_tokens"
    )


class GenAiMetrics(callbacks.BaseCallbackHandler):
    """Records every chat call of one model (GenAI semantic conventions).

    Called inline (``run_inline``) for sync and async calls alike: it only
    reads a clock and records a point.
    """

    run_inline = True

    def __init__(self, model: str) -> None:
        """Measures calls to the gateway alias ``model``."""
        self._model = model
        self._started: dict[uuid.UUID, float] = {}

    def _attributes(self, error: str | None = None) -> dict[str, str]:
        found = {
            "gen_ai.operation.name": "chat",
            "gen_ai.provider.name": _PROVIDER,
            "gen_ai.request.model": self._model,
        }
        if error is not None:
            found["error.type"] = error
        return found

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        """Starts the clock of one call."""
        del serialized, messages, kwargs
        self._started[run_id] = time.monotonic()

    def on_llm_end(
        self, response: outputs.LLMResult, *, run_id: uuid.UUID, **kwargs: Any
    ) -> None:
        """Records the call's duration and tokens."""
        del kwargs
        started = self._started.pop(run_id, None)
        instruments = _instruments()
        attributes = self._attributes()
        if started is not None:
            instruments["duration"].record(
                time.monotonic() - started, attributes
            )
        input_tokens, output_tokens = _usage(response)
        for kind, count in (("input", input_tokens), ("output", output_tokens)):
            if count is not None:
                instruments["tokens"].record(
                    count, dict(attributes, **{"gen_ai.token.type": kind})
                )

    def on_llm_error(
        self, error: BaseException, *, run_id: uuid.UUID, **kwargs: Any
    ) -> None:
        """Records a failed call's duration with its error type."""
        del kwargs
        started = self._started.pop(run_id, None)
        if started is not None:
            _instruments()["duration"].record(
                time.monotonic() - started,
                self._attributes(type(error).__name__),
            )
