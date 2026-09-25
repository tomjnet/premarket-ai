"""vendor-sim HTTP API: the "external news vendor".

GET /feed?date=YYYY-MM-DD returns the day's 100 synthetic items. Labels are
written to DATA_DIR/<date>/labels.jsonl for the eval harness and are never
returned by the API.

Settings are read once, from the environment: VENDOR_SEED, VENDOR_MIX and
DATA_DIR (no labels are written when it is empty).
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import pathlib
from typing import Annotated, Any

import fastapi

import vendor_sim
from vendor_sim import generator

_log = logging.getLogger(__name__)

_VENDOR_NAME = "Acme Market Wire (simulated)"
_SEED = int(os.environ.get("VENDOR_SEED", "42"))
_MIX = generator.FeedMix.parse(os.environ.get("VENDOR_MIX", ""))
_DATA_DIR = os.environ.get("DATA_DIR", "")

app = fastapi.FastAPI(
    title="premarket-ai vendor-sim", version=vendor_sim.__version__
)


def write_labels(feed: generator.Feed, data_dir: pathlib.Path) -> pathlib.Path:
    """Writes the feed's labels as JSON Lines.

    Args:
        feed: The feed whose labels are written.
        data_dir: The base folder. The file goes to
            ``data_dir/<feed date>/labels.jsonl``, replacing any earlier one.

    Returns:
        The path of the written file.
    """
    out_dir = data_dir / feed.feed_date.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "labels.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for label in feed.labels:
            f.write(json.dumps(label.to_json()) + "\n")
    return path


@app.get("/health")
def health() -> dict[str, Any]:
    """Reports that the vendor is up, with its seed and daily item count."""
    return {"status": "ok", "seed": _SEED, "items_per_day": _MIX.total}


@app.get("/feed")
def feed(
    day: Annotated[datetime.date | None, fastapi.Query(alias="date")] = None,
) -> dict[str, Any]:
    """Serves one day's feed, without its labels.

    Args:
        day: The feed date (query parameter ``date``). Defaults to today in
            New York.

    Returns:
        The feed envelope: date, vendor, item count and the items.
    """
    if day is None:
        day = generator.today_new_york()
    result = generator.generate_feed(day, _SEED, _MIX)
    if _DATA_DIR:
        write_labels(result, pathlib.Path(_DATA_DIR))
    _log.info("served feed %s with %d items", day, len(result.items))
    return {
        "feed_date": day.isoformat(),
        "vendor": _VENDOR_NAME,
        "synthetic": True,
        "count": len(result.items),
        "items": [item.to_json() for item in result.items],
    }
