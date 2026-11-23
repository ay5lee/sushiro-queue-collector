from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

# Hong Kong observes UTC+8 year-round (no DST).
HK_TZ = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class BusinessHours:
    open_minutes: int
    close_minutes: int
    close_fri_sat_minutes: int | None = None


def _parse_hhmm(value: str) -> int:
    hour_s, minute_s = value.strip().split(":", 1)
    hour = int(hour_s)
    minute = int(minute_s)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid HH:MM: {value!r}")
    return hour * 60 + minute


def _minutes_from_override(raw: dict[str, Any], key: str) -> int | None:
    if key not in raw:
        return None
    value = raw[key]
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return _parse_hhmm(value)
    raise ValueError(f"unsupported hours value for {key}: {value!r}")


def build_default_hours(open_time: str, close_time: str) -> BusinessHours:
    return BusinessHours(
        open_minutes=_parse_hhmm(open_time),
        close_minutes=_parse_hhmm(close_time),
    )


def resolve_store_hours(
    store_id: str,
    default: BusinessHours,
    overrides: dict[str, Any],
) -> BusinessHours:
    raw = overrides.get(store_id) or overrides.get(str(store_id))
    if not isinstance(raw, dict):
        return default
    open_m = _minutes_from_override(raw, "open")
    close_m = _minutes_from_override(raw, "close")
    fri_sat = _minutes_from_override(raw, "close_fri_sat")
    return BusinessHours(
        open_minutes=open_m if open_m is not None else default.open_minutes,
        close_minutes=close_m if close_m is not None else default.close_minutes,
        close_fri_sat_minutes=fri_sat
        if fri_sat is not None
        else default.close_fri_sat_minutes,
    )


def hk_now(now: datetime | None = None) -> datetime:
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(HK_TZ)


def is_within_hours(hours: BusinessHours, now: datetime | None = None) -> bool:
    local = hk_now(now)
    mins = local.hour * 60 + local.minute
    day = local.weekday()  # Mon=0 ... Sun=6; Fri=4 Sat=5
    close = (
        hours.close_fri_sat_minutes
        if day in (4, 5) and hours.close_fri_sat_minutes is not None
        else hours.close_minutes
    )
    return hours.open_minutes <= mins < close


def any_store_within_hours(
    store_ids: list[str],
    default: BusinessHours,
    overrides: dict[str, Any],
    now: datetime | None = None,
) -> bool:
    if not store_ids:
        return is_within_hours(default, now)
    return any(
        is_within_hours(resolve_store_hours(store_id, default, overrides), now)
        for store_id in store_ids
    )


def seconds_until_next_open(
    hours: BusinessHours,
    now: datetime | None = None,
) -> float:
    """Seconds until the next open instant under default daily hours."""
    local = hk_now(now)
    mins = local.hour * 60 + local.minute
    open_m = hours.open_minutes
    close_m = hours.close_minutes

    if open_m <= mins < close_m:
        return 0.0

    # Before open today
    if mins < open_m:
        delta_mins = open_m - mins
    else:
        # After close → next day's open
        delta_mins = (24 * 60 - mins) + open_m

    # Align to next minute boundary roughly
    return float(delta_mins * 60 - local.second)
