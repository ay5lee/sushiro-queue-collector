#!/usr/bin/env python3
"""Print expected wait (store × HKT weekday × hour) and optional leave-by.

Requires DATABASE_URL. Uses the same aggregation as sql/002_wait_baselines.sql
(inline; no need to create the view first).

Examples:
  export DATABASE_URL=postgresql://sushiro:sushiro@127.0.0.1:5432/sushiro_queue
  python scripts/wait_baseline.py --store-id 7
  python scripts/wait_baseline.py --store-id 7 --travel-minutes 25 --arrive 19:00
  python scripts/wait_baseline.py --store-id 7 --at 2026-11-27T19:30:00+08:00 --p75
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from psycopg import connect
from psycopg.rows import dict_row

from poller.baselines import (
    BASELINE_LOOKUP_SQL,
    CREATE_WAIT_BASELINES_VIEW_SQL,
    format_baseline_row,
    hk_dow_sunday0,
    resolve_query_local,
)
from poller.hours import HK_TZ


def _parse_at(value: str) -> datetime:
    """Parse ISO datetime; naive values are treated as Asia/Hong_Kong."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=HK_TZ)
    return dt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="v1 wait baseline: expected wait + optional leave-by"
    )
    parser.add_argument("--store-id", required=True, help="SUSHI-PASS store_id")
    parser.add_argument(
        "--at",
        type=_parse_at,
        default=None,
        help="Local/ISO datetime for the bucket (default: now HKT)",
    )
    parser.add_argument(
        "--arrive",
        metavar="HH:MM",
        default=None,
        help="Target arrival wall time in HKT (same calendar day as --at / now)",
    )
    parser.add_argument(
        "--travel-minutes",
        type=float,
        default=None,
        help="Travel time to the store; with --arrive, prints leave_at",
    )
    parser.add_argument(
        "--p75",
        action="store_true",
        help="Use p75 instead of median as expected wait",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Postgres URL (default: DATABASE_URL env)",
    )
    parser.add_argument(
        "--apply-view",
        action="store_true",
        help="Also CREATE OR REPLACE VIEW wait_baselines from sql/002_wait_baselines.sql",
    )
    args = parser.parse_args(argv)

    if (args.travel_minutes is None) ^ (args.arrive is None):
        parser.error("--travel-minutes and --arrive must be used together")

    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: set DATABASE_URL or pass --database-url", file=sys.stderr)
        return 2

    local = resolve_query_local(args.at, arrive_hhmm=args.arrive)
    dow = hk_dow_sunday0(local)
    hour = local.hour

    with connect(database_url, row_factory=dict_row) as conn:
        if args.apply_view:
            # Single statement (psycopg execute); full file + COMMENT via psql -f.
            conn.execute(CREATE_WAIT_BASELINES_VIEW_SQL)
            print("applied_view=wait_baselines", file=sys.stderr)

        row = conn.execute(
            BASELINE_LOOKUP_SQL,
            {"store_id": args.store_id, "dow": dow, "hour": hour},
        ).fetchone()

    arrive = local if args.arrive else None
    print(
        format_baseline_row(
            row,
            store_id=args.store_id,
            local=local,
            travel_minutes=args.travel_minutes,
            arrive=arrive,
            use_p75=args.p75,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
