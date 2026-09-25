"""vendor-sim command line.

Usage:

    vendor-sim summary --date 2026-09-24      counts per label kind
    vendor-sim labels  --date 2026-09-24 --out labels.jsonl
    vendor-sim feed    --date 2026-09-24      the feed JSON on stdout
    vendor-sim health                          exit 0 if the API answers
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import pathlib
import sys
import urllib.request

from vendor_sim import generator


def _health() -> int:
    """Calls the API's /health; returns the process exit code."""
    # Container healthcheck: argv without spaces survives every engine.
    url = os.environ.get("HEALTH_URL", "http://127.0.0.1:8080/health")
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return 0 if response.status == 200 else 1
    except OSError as error:
        print(f"health check failed: {error}", file=sys.stderr)
        return 1


def _print_summary(feed: generator.Feed) -> None:
    """Prints the number of items per label kind and duplicate type."""
    kinds = collections.Counter(label.kind for label in feed.labels)
    dups = collections.Counter(
        label.dup_type for label in feed.labels if label.dup_type
    )
    print(f"feed {feed.feed_date}: {len(feed.items)} items")
    for kind, count in sorted(kinds.items()):
        print(f"  {kind:<11} {count}")
    by_type = ", ".join(
        f"{name} {count}" for name, count in sorted(dups.items())
    )
    print(f"  duplicates by type: {by_type}")


def main(argv: list[str] | None = None) -> int:
    """Runs one vendor-sim command.

    Args:
        argv: The arguments after the program name. None means
            ``sys.argv[1:]``.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(prog="vendor-sim")
    parser.add_argument(
        "command", choices=("summary", "labels", "feed", "health")
    )
    parser.add_argument(
        "--date", type=datetime.date.fromisoformat, default=None
    )
    parser.add_argument(
        "--seed", type=int, default=int(os.environ.get("VENDOR_SEED", "42"))
    )
    parser.add_argument("--mix", default=os.environ.get("VENDOR_MIX", ""))
    parser.add_argument("--out", type=pathlib.Path, default=None)
    args = parser.parse_args(argv)

    if args.command == "health":
        return _health()

    day = args.date
    if day is None:
        day = generator.today_new_york()
    feed = generator.generate_feed(
        day, args.seed, generator.FeedMix.parse(args.mix)
    )

    if args.command == "feed":
        items = [item.to_json() for item in feed.items]
        json.dump(items, sys.stdout, indent=2)
        sys.stdout.write("\n")
    elif args.command == "labels":
        lines = "".join(
            json.dumps(label.to_json()) + "\n" for label in feed.labels
        )
        if args.out is None:
            sys.stdout.write(lines)
        else:
            args.out.write_text(lines, encoding="utf-8")
    else:
        _print_summary(feed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
