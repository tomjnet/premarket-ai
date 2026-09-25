"""vendor-sim command line.

vendor-sim summary --date 2026-09-24      counts per label kind
vendor-sim labels  --date 2026-09-24 --out labels.jsonl
vendor-sim feed    --date 2026-09-24      the feed JSON on stdout
vendor-sim health                          exit 0 if the API answers /health
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

from vendor_sim.generator import FeedMix, generate_feed, today_new_york


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vendor-sim")
    parser.add_argument("command", choices=("summary", "labels", "feed", "health"))
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    parser.add_argument("--seed", type=int, default=int(os.environ.get("VENDOR_SEED", "42")))
    parser.add_argument("--mix", default=os.environ.get("VENDOR_MIX", ""))
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.command == "health":
        # Container healthcheck: argv without spaces survives every engine.
        url = os.environ.get("HEALTH_URL", "http://127.0.0.1:8080/health")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return 0 if response.status == 200 else 1
        except OSError as error:
            print(f"health check failed: {error}", file=sys.stderr)
            return 1

    day = args.date or today_new_york()
    feed = generate_feed(day, args.seed, FeedMix.parse(args.mix))

    if args.command == "feed":
        json.dump([item.to_json() for item in feed.items], sys.stdout, indent=2)
        sys.stdout.write("\n")
    elif args.command == "labels":
        lines = "".join(json.dumps(label.to_json()) + "\n" for label in feed.labels)
        if args.out:
            args.out.write_text(lines, encoding="utf-8")
        else:
            sys.stdout.write(lines)
    else:
        kinds = Counter(label.kind for label in feed.labels)
        dups = Counter(label.dup_type for label in feed.labels if label.dup_type)
        print(f"feed {day}: {len(feed.items)} items")
        for kind, count in sorted(kinds.items()):
            print(f"  {kind:<11} {count}")
        print("  duplicates by type: " + ", ".join(f"{k} {v}" for k, v in sorted(dups.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
