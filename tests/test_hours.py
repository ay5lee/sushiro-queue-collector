from datetime import datetime, timezone

from poller.hours import (
    build_default_hours,
    is_within_hours,
    resolve_store_hours,
)


def test_default_window_midday_hk():
    hours = build_default_hours("10:30", "22:00")
    # 2026-11-24 12:00 HKT = 04:00 UTC
    noon = datetime(2026, 11, 24, 4, 0, tzinfo=timezone.utc)
    assert is_within_hours(hours, noon) is True


def test_default_window_overnight_hk():
    hours = build_default_hours("10:30", "22:00")
    # 2026-11-24 04:50 HKT = 2026-11-23 20:50 UTC
    night = datetime(2026, 11, 23, 20, 50, tzinfo=timezone.utc)
    assert is_within_hours(hours, night) is False


def test_store_override_fri_sat_close():
    default = build_default_hours("10:30", "22:00")
    hours = resolve_store_hours(
        "18",
        default,
        {"18": {"open": "10:30", "close": "22:00", "close_fri_sat": "22:30"}},
    )
    # Friday 22:15 HKT = 14:15 UTC (still open with close_fri_sat 22:30)
    fri_late = datetime(2026, 11, 27, 14, 15, tzinfo=timezone.utc)
    assert is_within_hours(hours, fri_late) is True
