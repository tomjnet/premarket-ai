"""vendor-sim HTTP API: the "external news vendor".

GET /feed?date=YYYY-MM-DD returns the day's 100 synthetic items. Labels are
written to DATA_DIR/<date>/labels.jsonl for the eval harness and are never
returned by the API.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Query

from vendor_sim import __version__
from vendor_sim.generator import Feed, FeedMix, generate_feed, today_new_york

log = logging.getLogger("vendor_sim")

VENDOR_NAME = "Acme Market Wire (simulated)"
SEED = int(os.environ.get("VENDOR_SEED", "42"))
MIX = FeedMix.parse(os.environ.get("VENDOR_MIX", ""))
DATA_DIR = os.environ.get("DATA_DIR", "")

app = FastAPI(title="premarket-ai vendor-sim", version=__version__)


def write_labels(feed: Feed, data_dir: Path) -> Path:
    """Writes labels.jsonl for ``feed`` under ``data_dir/<date>/``."""
    out_dir = data_dir / feed.feed_date.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "labels.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for label in feed.labels:
            f.write(json.dumps(label.to_json()) + "\n")
    return path


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "seed": SEED, "items_per_day": MIX.total}


@app.get("/feed")
def feed(day: Annotated[date | None, Query(alias="date")] = None) -> dict:
    day = day or today_new_york()
    result = generate_feed(day, SEED, MIX)
    if DATA_DIR:
        write_labels(result, Path(DATA_DIR))
    log.info("served feed %s with %d items", day, len(result.items))
    return {
        "feed_date": day.isoformat(),
        "vendor": VENDOR_NAME,
        "synthetic": True,
        "count": len(result.items),
        "items": [item.to_json() for item in result.items],
    }
