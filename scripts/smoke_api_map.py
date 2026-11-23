#!/usr/bin/env python3
"""Smoke-test SUSHI-PASS field mapping without Postgres/Docker.

Usage:
  python scripts/smoke_api_map.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

from poller.mapping import (
    extract_called_number,
    map_queue_metrics,
    map_store,
    normalize_storelist,
)

BASE = "https://sushipass.sushiro.com.hk"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    ),
    "Accept": "application/json",
}


def main() -> int:
    with httpx.Client(headers=HEADERS, timeout=20.0) as client:
        storelist = client.get(
            f"{BASE}/api/2.0/info/storelist",
            params={
                "latitude": "22",
                "longitude": "114",
                "numresults": "100",
                "region": "HK",
            },
        )
        storelist.raise_for_status()
        stores = normalize_storelist(storelist.json())
        print(f"storelist_count={len(stores)}")
        if not stores:
            print("ERROR: empty storelist")
            return 1

        sample = map_store(stores[0])
        print(
            json.dumps(
                {
                    "store_id": sample.store_id,
                    "name_en": sample.name_en,
                    "name_zh": sample.name_zh,
                    "wait_minutes": sample.wait_minutes,
                    "waiting_group": sample.waiting_group,
                    "store_status": sample.store_status,
                },
                ensure_ascii=False,
            )
        )

        store_id = sample.store_id
        gq = client.get(
            f"{BASE}/api/2.0/remote/groupqueues",
            params={"region": "HK", "storeid": store_id},
        )
        gq.raise_for_status()
        payload = gq.json()
        metrics = map_queue_metrics(
            wait_minutes=sample.wait_minutes,
            waiting_group=sample.waiting_group,
            groupqueues=payload,
        )
        print(
            json.dumps(
                {
                    "groupqueues_keys": sorted(payload.keys()),
                    "called_number": metrics.called_number,
                    "queue_number": metrics.queue_number,
                    "wait_minutes": metrics.wait_minutes,
                    "extract_called_number": extract_called_number(payload),
                    "groupqueues_sample": payload,
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
