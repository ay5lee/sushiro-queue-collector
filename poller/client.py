from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings
from .logging_util import log_extra

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-HK,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}


@dataclass
class HttpResult:
    ok: bool
    status_code: int | None
    data: Any | None
    error: str | None
    url: str


class RateLimiter:
    """Simple sliding-window request ceiling across the process."""

    def __init__(self, max_per_minute: int) -> None:
        self.max_per_minute = max(1, max_per_minute)
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                cutoff = now - 60.0
                self._timestamps = [t for t in self._timestamps if t >= cutoff]
                if len(self._timestamps) < self.max_per_minute:
                    self._timestamps.append(now)
                    return
                sleep_for = 60.0 - (now - self._timestamps[0]) + 0.05
                await asyncio.sleep(max(sleep_for, 0.05))


class SushiPassClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.rate_limiter = RateLimiter(settings.max_requests_per_minute)
        self._client = httpx.AsyncClient(
            base_url=settings.sushi_pass_base_url,
            headers=DEFAULT_HEADERS,
            timeout=settings.request_timeout_seconds,
            follow_redirects=True,
        )
        self._global_backoff_until = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _wait_global_backoff(self) -> None:
        delay = self._global_backoff_until - time.monotonic()
        if delay > 0:
            log_extra(
                logger,
                logging.WARNING,
                "global_backoff_sleep",
                seconds=round(delay, 2),
            )
            await asyncio.sleep(delay)

    def _set_global_backoff(self, seconds: float) -> None:
        self._global_backoff_until = max(
            self._global_backoff_until, time.monotonic() + seconds
        )

    async def _request_json(self, path: str, params: dict[str, Any]) -> HttpResult:
        url = f"{self.settings.sushi_pass_base_url}{path}"
        attempt = 0
        while True:
            attempt += 1
            await self._wait_global_backoff()
            await self.rate_limiter.acquire()
            try:
                response = await self._client.get(path, params=params)
            except httpx.TimeoutException as exc:
                error = f"timeout: {exc}"
                backoff = self._backoff_seconds(attempt)
                self._set_global_backoff(backoff)
                log_extra(
                    logger,
                    logging.WARNING,
                    "request_timeout",
                    url=url,
                    attempt=attempt,
                    backoff_seconds=backoff,
                )
                if attempt >= 4:
                    return HttpResult(False, None, None, error, url)
                await asyncio.sleep(backoff)
                continue
            except httpx.HTTPError as exc:
                error = f"http_error: {exc}"
                backoff = self._backoff_seconds(attempt)
                self._set_global_backoff(backoff)
                log_extra(
                    logger,
                    logging.WARNING,
                    "request_error",
                    url=url,
                    attempt=attempt,
                    error=error,
                    backoff_seconds=backoff,
                )
                if attempt >= 4:
                    return HttpResult(False, None, None, error, url)
                await asyncio.sleep(backoff)
                continue

            if response.status_code in {429} or response.status_code >= 500:
                backoff = self._backoff_seconds(attempt)
                self._set_global_backoff(backoff)
                log_extra(
                    logger,
                    logging.WARNING,
                    "request_retryable_status",
                    url=url,
                    status=response.status_code,
                    attempt=attempt,
                    backoff_seconds=backoff,
                )
                if attempt >= 4:
                    return HttpResult(
                        False,
                        response.status_code,
                        None,
                        f"http_{response.status_code}",
                        url,
                    )
                await asyncio.sleep(backoff)
                continue

            if response.status_code >= 400:
                return HttpResult(
                    False,
                    response.status_code,
                    None,
                    f"http_{response.status_code}",
                    url,
                )

            try:
                data = response.json()
            except ValueError:
                return HttpResult(
                    False,
                    response.status_code,
                    None,
                    "invalid_json",
                    url,
                )
            return HttpResult(True, response.status_code, data, None, url)

    def _backoff_seconds(self, attempt: int) -> float:
        base = self.settings.backoff_initial_seconds * (2 ** (attempt - 1))
        capped = min(base, self.settings.backoff_max_seconds)
        jitter = random.uniform(0, capped * 0.25)
        return capped + jitter

    async def fetch_storelist(self) -> HttpResult:
        return await self._request_json(
            "/api/2.0/info/storelist",
            {
                "latitude": self.settings.storelist_latitude,
                "longitude": self.settings.storelist_longitude,
                "numresults": self.settings.storelist_numresults,
                "region": self.settings.storelist_region,
            },
        )

    async def fetch_groupqueues(self, store_id: str) -> HttpResult:
        return await self._request_json(
            "/api/2.0/remote/groupqueues",
            {
                "region": self.settings.storelist_region,
                "storeid": store_id,
            },
        )
