"""v1 wait-time baselines helpers (store × DOW × hour median / leave-by)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .hours import HK_TZ, hk_now

# Matches sql/002_wait_baselines.sql (inline so CLI works before the view exists).
BASELINE_LOOKUP_SQL = """
SELECT
    store_id,
    EXTRACT(DOW FROM polled_at AT TIME ZONE 'Asia/Hong_Kong')::smallint AS dow,
    EXTRACT(HOUR FROM polled_at AT TIME ZONE 'Asia/Hong_Kong')::smallint AS hour,
    COUNT(*)::bigint AS sample_count,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY wait_minutes)::double precision
        AS wait_median,
    percentile_cont(0.75) WITHIN GROUP (ORDER BY wait_minutes)::double precision
        AS wait_p75
FROM queue_snapshots
WHERE error IS NULL
  AND wait_minutes IS NOT NULL
  AND store_id = %(store_id)s
  AND EXTRACT(DOW FROM polled_at AT TIME ZONE 'Asia/Hong_Kong') = %(dow)s
  AND EXTRACT(HOUR FROM polled_at AT TIME ZONE 'Asia/Hong_Kong') = %(hour)s
GROUP BY 1, 2, 3
"""

CREATE_WAIT_BASELINES_VIEW_SQL = """
CREATE OR REPLACE VIEW wait_baselines AS
SELECT
    store_id,
    EXTRACT(DOW FROM polled_at AT TIME ZONE 'Asia/Hong_Kong')::smallint AS dow,
    EXTRACT(HOUR FROM polled_at AT TIME ZONE 'Asia/Hong_Kong')::smallint AS hour,
    COUNT(*)::bigint AS sample_count,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY wait_minutes)::double precision
        AS wait_median,
    percentile_cont(0.75) WITHIN GROUP (ORDER BY wait_minutes)::double precision
        AS wait_p75
FROM queue_snapshots
WHERE error IS NULL
  AND wait_minutes IS NOT NULL
GROUP BY 1, 2, 3
"""


def hk_dow_sunday0(local: datetime) -> int:
    """PostgreSQL EXTRACT(DOW): Sunday=0 … Saturday=6."""
    # Python weekday(): Monday=0 … Sunday=6
    return (local.weekday() + 1) % 7


def parse_arrive_hhmm(value: str, *, on_date: datetime) -> datetime:
    """Parse HH:MM as Asia/Hong_Kong wall time on the same calendar day as on_date."""
    hour_s, minute_s = value.strip().split(":", 1)
    hour = int(hour_s)
    minute = int(minute_s)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid HH:MM: {value!r}")
    local = on_date.astimezone(HK_TZ) if on_date.tzinfo else on_date.replace(tzinfo=HK_TZ)
    return local.replace(hour=hour, minute=minute, second=0, microsecond=0)


def leave_at(
    *,
    arrive: datetime,
    travel_minutes: float,
    expected_wait_minutes: float,
) -> datetime:
    """leave_at ≈ target_arrive − travel_minutes − expected_wait."""
    return arrive - timedelta(minutes=travel_minutes + expected_wait_minutes)


def resolve_query_local(
    at: datetime | None = None,
    *,
    arrive_hhmm: str | None = None,
) -> datetime:
    """Local HKT datetime used for DOW/hour bucket (arrive time if given, else now/at)."""
    base = hk_now(at)
    if arrive_hhmm:
        return parse_arrive_hhmm(arrive_hhmm, on_date=base)
    return base


def format_baseline_row(
    row: dict[str, Any] | None,
    *,
    store_id: str,
    local: datetime,
    travel_minutes: float | None = None,
    arrive: datetime | None = None,
    use_p75: bool = False,
) -> str:
    lines: list[str] = [
        f"store_id={store_id}",
        f"local_hkt={local.isoformat()}",
        f"dow={hk_dow_sunday0(local)} hour={local.hour}",
    ]
    if row is None:
        lines.append("baseline=none (no samples for this store×dow×hour)")
        return "\n".join(lines)

    median = float(row["wait_median"])
    p75 = float(row["wait_p75"])
    expected = p75 if use_p75 else median
    lines.extend(
        [
            f"sample_count={row['sample_count']}",
            f"wait_median_minutes={median:.1f}",
            f"wait_p75_minutes={p75:.1f}",
            f"expected_wait_minutes={expected:.1f}"
            + (" (p75)" if use_p75 else " (median)"),
        ]
    )
    if travel_minutes is not None and arrive is not None:
        leave = leave_at(
            arrive=arrive,
            travel_minutes=travel_minutes,
            expected_wait_minutes=expected,
        )
        lines.extend(
            [
                f"arrive_hkt={arrive.isoformat()}",
                f"travel_minutes={travel_minutes:g}",
                f"leave_at_hkt={leave.isoformat()}",
            ]
        )
    return "\n".join(lines)
