from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return float(raw)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str = "postgresql://sushiro:sushiro@db:5432/sushiro_queue"
    sushi_pass_base_url: str = "https://sushipass.sushiro.com.hk"
    storelist_latitude: str = "22"
    storelist_longitude: str = "114"
    storelist_numresults: int = 100
    storelist_region: str = "HK"

    sweep_interval_seconds: float = 60.0
    store_sync_interval_seconds: float = 21600.0
    concurrency: int = 4
    request_timeout_seconds: float = 12.0
    max_requests_per_minute: int = 90

    backoff_initial_seconds: float = 2.0
    backoff_max_seconds: float = 300.0
    circuit_break_failure_ratio: float = 0.5
    circuit_break_min_samples: int = 10
    circuit_break_cooldown_seconds: float = 300.0

    default_open_time: str = "10:30"
    default_close_time: str = "22:00"
    store_hours_overrides: dict[str, Any] = field(default_factory=dict)
    force_poll: bool = False

    log_level: str = "INFO"
    log_json: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        overrides_raw = _env("STORE_HOURS_JSON", "")
        overrides: dict[str, Any] = {}
        if overrides_raw.strip():
            parsed = json.loads(overrides_raw)
            if not isinstance(parsed, dict):
                raise ValueError("STORE_HOURS_JSON must be a JSON object")
            overrides = parsed

        concurrency = max(1, min(8, _env_int("CONCURRENCY", 4)))
        return cls(
            database_url=_env(
                "DATABASE_URL",
                "postgresql://sushiro:sushiro@db:5432/sushiro_queue",
            ),
            sushi_pass_base_url=_env(
                "SUSHI_PASS_BASE_URL", "https://sushipass.sushiro.com.hk"
            ).rstrip("/"),
            storelist_latitude=_env("STORELIST_LATITUDE", "22"),
            storelist_longitude=_env("STORELIST_LONGITUDE", "114"),
            storelist_numresults=_env_int("STORELIST_NUMRESULTS", 100),
            storelist_region=_env("STORELIST_REGION", "HK"),
            sweep_interval_seconds=_env_float("SWEEP_INTERVAL_SECONDS", 60.0),
            store_sync_interval_seconds=_env_float(
                "STORE_SYNC_INTERVAL_SECONDS", 21600.0
            ),
            concurrency=concurrency,
            request_timeout_seconds=_env_float("REQUEST_TIMEOUT_SECONDS", 12.0),
            max_requests_per_minute=_env_int("MAX_REQUESTS_PER_MINUTE", 90),
            backoff_initial_seconds=_env_float("BACKOFF_INITIAL_SECONDS", 2.0),
            backoff_max_seconds=_env_float("BACKOFF_MAX_SECONDS", 300.0),
            circuit_break_failure_ratio=_env_float(
                "CIRCUIT_BREAK_FAILURE_RATIO", 0.5
            ),
            circuit_break_min_samples=_env_int("CIRCUIT_BREAK_MIN_SAMPLES", 10),
            circuit_break_cooldown_seconds=_env_float(
                "CIRCUIT_BREAK_COOLDOWN_SECONDS", 300.0
            ),
            default_open_time=_env("DEFAULT_OPEN_TIME", "10:30"),
            default_close_time=_env("DEFAULT_CLOSE_TIME", "22:00"),
            store_hours_overrides=overrides,
            force_poll=_env_bool("FORCE_POLL", False),
            log_level=_env("LOG_LEVEL", "INFO").upper(),
            log_json=_env_bool("LOG_JSON", True),
        )
