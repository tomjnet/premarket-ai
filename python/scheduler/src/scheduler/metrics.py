"""The scheduler's Prometheus metrics (scraped by Prometheus, increment 6).

- ``premarket_sla_ok{check}``: 1 when the day's SLA check passed, 0 when
  it was breached (``ingest``, ``backlog``, ``verify``, ``brief``).
- ``premarket_job_status{job}``: the last run's outcome (1 DONE, 0 FAILED,
  -1 SKIPPED).
- ``premarket_job_duration_seconds{job}``: how long the last run took.
- ``premarket_job_last_success_timestamp_seconds{job}``.
- ``premarket_scheduler_heartbeat_timestamp_seconds``: the service loop.
"""

from __future__ import annotations

import time

import prometheus_client

REGISTRY = prometheus_client.CollectorRegistry()

SLA_OK = prometheus_client.Gauge(
    "premarket_sla_ok",
    "1 when today's SLA check passed, 0 when it was breached.",
    ["check"],
    registry=REGISTRY,
)
JOB_STATUS = prometheus_client.Gauge(
    "premarket_job_status",
    "Last run of a scheduled job: 1 DONE, 0 FAILED, -1 SKIPPED.",
    ["job"],
    registry=REGISTRY,
)
JOB_DURATION = prometheus_client.Gauge(
    "premarket_job_duration_seconds",
    "Duration of the last run of a scheduled job.",
    ["job"],
    registry=REGISTRY,
)
JOB_SUCCESS = prometheus_client.Gauge(
    "premarket_job_last_success_timestamp_seconds",
    "When a scheduled job last finished DONE (Unix time).",
    ["job"],
    registry=REGISTRY,
)
HEARTBEAT = prometheus_client.Gauge(
    "premarket_scheduler_heartbeat_timestamp_seconds",
    "The scheduler loop's last heartbeat (Unix time).",
    registry=REGISTRY,
)

_STATUS_VALUE = {"DONE": 1, "FAILED": 0, "SKIPPED": -1}


def job_finished(job: str, status: str, seconds: float) -> None:
    """Records one job run."""
    JOB_STATUS.labels(job).set(_STATUS_VALUE.get(status, 0))
    JOB_DURATION.labels(job).set(seconds)
    if status == "DONE":
        JOB_SUCCESS.labels(job).set(time.time())


def sla_checked(check: str, ok: bool) -> None:
    """Records one SLA check."""
    SLA_OK.labels(check).set(1 if ok else 0)


def serve(port: int) -> None:
    """Serves ``/metrics`` on ``port`` (a background thread)."""
    prometheus_client.start_http_server(port, registry=REGISTRY)
