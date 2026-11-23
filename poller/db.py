from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .mapping import StoreRow
from .logging_util import log_extra

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "sql" / "001_schema.sql"


class Database:
    def __init__(self, database_url: str) -> None:
        self.pool = ConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row, "autocommit": True},
            open=True,
        )

    def close(self) -> None:
        self.pool.close()

    def wait_ready(self, attempts: int = 30) -> None:
        last_error: Exception | None = None
        for _ in range(attempts):
            try:
                with self.pool.connection() as conn:
                    conn.execute("SELECT 1")
                return
            except Exception as exc:  # noqa: BLE001 — retry until Postgres is up
                last_error = exc
                import time

                time.sleep(1)
        raise RuntimeError(f"database not ready: {last_error}")

    def apply_schema(self) -> None:
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        with self.pool.connection() as conn:
            conn.execute(sql)
        log_extra(logger, logging.INFO, "schema_applied", path=str(SCHEMA_PATH))

    def upsert_stores(self, stores: Iterable[StoreRow]) -> list[str]:
        rows = list(stores)
        if not rows:
            return []
        seen_ids = [row.store_id for row in rows]
        now = datetime.now(timezone.utc)
        with self.pool.connection() as conn:
            with conn.transaction():
                for row in rows:
                    conn.execute(
                        """
                        INSERT INTO stores (
                            store_id, name_en, name_zh, region, latitude, longitude,
                            address, is_active, raw_json, first_seen_at, last_seen_at
                        ) VALUES (
                            %(store_id)s, %(name_en)s, %(name_zh)s, %(region)s,
                            %(latitude)s, %(longitude)s, %(address)s, true,
                            %(raw_json)s, %(now)s, %(now)s
                        )
                        ON CONFLICT (store_id) DO UPDATE SET
                            name_en = EXCLUDED.name_en,
                            name_zh = EXCLUDED.name_zh,
                            region = EXCLUDED.region,
                            latitude = EXCLUDED.latitude,
                            longitude = EXCLUDED.longitude,
                            address = EXCLUDED.address,
                            is_active = true,
                            raw_json = EXCLUDED.raw_json,
                            last_seen_at = EXCLUDED.last_seen_at
                        """,
                        {
                            "store_id": row.store_id,
                            "name_en": row.name_en,
                            "name_zh": row.name_zh,
                            "region": row.region,
                            "latitude": row.latitude,
                            "longitude": row.longitude,
                            "address": row.address,
                            "raw_json": Jsonb(row.raw_json),
                            "now": now,
                        },
                    )
                conn.execute(
                    """
                    UPDATE stores
                    SET is_active = false
                    WHERE is_active = true
                      AND store_id <> ALL(%(ids)s)
                    """,
                    {"ids": seen_ids},
                )
        return seen_ids

    def list_active_store_ids(self) -> list[str]:
        with self.pool.connection() as conn:
            result = conn.execute(
                """
                SELECT store_id
                FROM stores
                WHERE is_active = true
                ORDER BY store_id
                """
            )
            return [row["store_id"] for row in result.fetchall()]

    def get_store_wait_fields(self, store_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not store_ids:
            return {}
        with self.pool.connection() as conn:
            result = conn.execute(
                """
                SELECT store_id, raw_json
                FROM stores
                WHERE store_id = ANY(%(ids)s)
                """,
                {"ids": store_ids},
            )
            out: dict[str, dict[str, Any]] = {}
            for row in result.fetchall():
                raw = row["raw_json"] or {}
                out[row["store_id"]] = {
                    "wait_minutes": raw.get("wait"),
                    "waiting_group": raw.get("waitingGroup"),
                    "store_status": raw.get("storeStatus"),
                    "raw_json": raw,
                }
            return out

    def insert_snapshot(
        self,
        *,
        store_id: str,
        polled_at: datetime,
        wait_minutes: int | None,
        queue_number: int | None,
        called_number: int | None,
        group_key: str | None,
        raw_json: dict[str, Any],
        http_status: int | None,
        error: str | None,
    ) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO queue_snapshots (
                    store_id, polled_at, wait_minutes, queue_number, called_number,
                    group_key, raw_json, http_status, error
                ) VALUES (
                    %(store_id)s, %(polled_at)s, %(wait_minutes)s, %(queue_number)s,
                    %(called_number)s, %(group_key)s, %(raw_json)s,
                    %(http_status)s, %(error)s
                )
                """,
                {
                    "store_id": store_id,
                    "polled_at": polled_at,
                    "wait_minutes": wait_minutes,
                    "queue_number": queue_number,
                    "called_number": called_number,
                    "group_key": group_key,
                    "raw_json": Jsonb(raw_json),
                    "http_status": http_status,
                    "error": error,
                },
            )
