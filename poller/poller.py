from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from .client import SushiPassClient
from .config import Settings
from .db import Database
from .hours import (
    any_store_within_hours,
    build_default_hours,
    resolve_store_hours,
    seconds_until_next_open,
    is_within_hours,
)
from .logging_util import log_extra
from .mapping import (
    map_queue_metrics,
    map_store,
    normalize_storelist,
)

logger = logging.getLogger(__name__)


class QueuePoller:
    def __init__(self, settings: Settings, db: Database, client: SushiPassClient) -> None:
        self.settings = settings
        self.db = db
        self.client = client
        self.default_hours = build_default_hours(
            settings.default_open_time, settings.default_close_time
        )
        self._last_store_sync = 0.0
        self._store_wait_cache: dict[str, dict[str, Any]] = {}
        self._consecutive_sweep_failures = 0

    async def run_forever(self) -> None:
        self.db.wait_ready()
        self.db.apply_schema()
        await self.sync_stores(reason="cold_start")

        while True:
            loop_started = time.monotonic()
            try:
                await self._maybe_pause_for_hours()
                await self._maybe_sync_stores()
                await self.run_sweep()
            except Exception:
                logger.exception("sweep_loop_error")
                self._consecutive_sweep_failures += 1

            elapsed = time.monotonic() - loop_started
            sleep_for = max(0.0, self.settings.sweep_interval_seconds - elapsed)
            log_extra(
                logger,
                logging.INFO,
                "sweep_interval_sleep",
                seconds=round(sleep_for, 2),
                consecutive_failures=self._consecutive_sweep_failures,
            )
            await asyncio.sleep(sleep_for)

    async def _maybe_pause_for_hours(self) -> None:
        if self.settings.force_poll:
            return

        store_ids = self.db.list_active_store_ids()
        if any_store_within_hours(
            store_ids,
            self.default_hours,
            self.settings.store_hours_overrides,
        ):
            return

        wait = seconds_until_next_open(self.default_hours)
        # Cap sleep chunks so FORCE_POLL / config changes can take effect.
        chunk = min(max(wait, 30.0), 900.0)
        log_extra(
            logger,
            logging.INFO,
            "outside_store_hours_pause",
            sleep_seconds=round(chunk, 1),
            next_open_eta_seconds=round(wait, 1),
            default_open=self.settings.default_open_time,
            default_close=self.settings.default_close_time,
        )
        await asyncio.sleep(chunk)

    async def _maybe_sync_stores(self) -> None:
        due = (
            time.monotonic() - self._last_store_sync
            >= self.settings.store_sync_interval_seconds
        )
        if due:
            await self.sync_stores(reason="interval")

    async def sync_stores(self, reason: str) -> list[str]:
        result = await self.client.fetch_storelist()
        if not result.ok or result.data is None:
            log_extra(
                logger,
                logging.ERROR,
                "store_sync_failed",
                reason=reason,
                status=result.status_code,
                error=result.error,
            )
            return self.db.list_active_store_ids()

        raw_stores = normalize_storelist(result.data)
        mapped = [map_store(item) for item in raw_stores]
        store_ids = self.db.upsert_stores(mapped)
        self._store_wait_cache = {
            row.store_id: {
                "wait_minutes": row.wait_minutes,
                "waiting_group": row.waiting_group,
                "store_status": row.store_status,
                "raw_json": row.raw_json,
            }
            for row in mapped
        }
        self._last_store_sync = time.monotonic()
        log_extra(
            logger,
            logging.INFO,
            "store_sync_ok",
            reason=reason,
            store_count=len(store_ids),
        )
        return store_ids

    async def run_sweep(self) -> None:
        # Refresh wait fields cheaply via one storelist call each sweep.
        await self.sync_stores(reason="sweep_wait_refresh")
        store_ids = self.db.list_active_store_ids()
        if not store_ids:
            log_extra(logger, logging.WARNING, "no_active_stores")
            return

        if not self.settings.force_poll:
            store_ids = [
                store_id
                for store_id in store_ids
                if is_within_hours(
                    resolve_store_hours(
                        store_id,
                        self.default_hours,
                        self.settings.store_hours_overrides,
                    )
                )
                or self._store_has_active_queue(store_id)
            ]

        if not store_ids:
            log_extra(logger, logging.INFO, "no_stores_in_hours")
            return

        sem = asyncio.Semaphore(self.settings.concurrency)
        successes = 0
        failures = 0

        async def one(store_id: str) -> None:
            nonlocal successes, failures
            async with sem:
                ok = await self._poll_store(store_id)
                if ok:
                    successes += 1
                else:
                    failures += 1

        await asyncio.gather(*(one(store_id) for store_id in store_ids))

        total = successes + failures
        failure_ratio = (failures / total) if total else 0.0
        if (
            total >= self.settings.circuit_break_min_samples
            and failure_ratio >= self.settings.circuit_break_failure_ratio
        ):
            self._consecutive_sweep_failures += 1
            cooldown = self.settings.circuit_break_cooldown_seconds
            log_extra(
                logger,
                logging.ERROR,
                "circuit_break",
                failures=failures,
                successes=successes,
                failure_ratio=round(failure_ratio, 3),
                cooldown_seconds=cooldown,
            )
            await asyncio.sleep(cooldown)
        else:
            self._consecutive_sweep_failures = 0

        log_extra(
            logger,
            logging.INFO,
            "sweep_complete",
            stores=total,
            successes=successes,
            failures=failures,
        )

    def _store_has_active_queue(self, store_id: str) -> bool:
        meta = self._store_wait_cache.get(store_id) or {}
        wait = meta.get("wait_minutes") or 0
        groups = meta.get("waiting_group") or 0
        try:
            return int(wait) > 0 or int(groups) > 0
        except (TypeError, ValueError):
            return False

    async def _poll_store(self, store_id: str) -> bool:
        polled_at = datetime.now(timezone.utc)
        meta = self._store_wait_cache.get(store_id) or {}
        wait_minutes = meta.get("wait_minutes")
        waiting_group = meta.get("waiting_group")
        try:
            wait_minutes = int(wait_minutes) if wait_minutes is not None else None
            if wait_minutes is not None and wait_minutes < 0:
                wait_minutes = None
        except (TypeError, ValueError):
            wait_minutes = None
        try:
            waiting_group = int(waiting_group) if waiting_group is not None else None
        except (TypeError, ValueError):
            waiting_group = None

        result = await self.client.fetch_groupqueues(store_id)
        if not result.ok or not isinstance(result.data, dict):
            self.db.insert_snapshot(
                store_id=store_id,
                polled_at=polled_at,
                wait_minutes=wait_minutes,
                queue_number=None,
                called_number=None,
                group_key="walkin",
                raw_json={
                    "storelist": meta.get("raw_json") or {},
                    "groupqueues": result.data,
                },
                http_status=result.status_code,
                error=result.error or "groupqueues_failed",
            )
            log_extra(
                logger,
                logging.WARNING,
                "store_poll_failed",
                store_id=store_id,
                status=result.status_code,
                error=result.error,
            )
            return False

        metrics = map_queue_metrics(
            wait_minutes=wait_minutes,
            waiting_group=waiting_group,
            groupqueues=result.data,
        )
        self.db.insert_snapshot(
            store_id=store_id,
            polled_at=polled_at,
            wait_minutes=metrics.wait_minutes,
            queue_number=metrics.queue_number,
            called_number=metrics.called_number,
            group_key=metrics.group_key,
            raw_json={
                "storelist": meta.get("raw_json") or {},
                "groupqueues": result.data,
                "derived": {
                    "waiting_group": metrics.waiting_group,
                    "queue_number_formula": "called_number + waitingGroup when both known",
                },
            },
            http_status=result.status_code,
            error=None,
        )
        return True
