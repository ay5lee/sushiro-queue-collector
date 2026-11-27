from datetime import datetime

from poller.baselines import (
    hk_dow_sunday0,
    leave_at,
    parse_arrive_hhmm,
    resolve_query_local,
)
from poller.hours import HK_TZ


def test_hk_dow_sunday0_matches_postgres() -> None:
    # 2026-11-27 is a Friday → PG DOW 5
    fri = datetime(2026, 11, 27, 19, 0, tzinfo=HK_TZ)
    assert hk_dow_sunday0(fri) == 5
    # Sunday
    sun = datetime(2026, 11, 29, 12, 0, tzinfo=HK_TZ)
    assert hk_dow_sunday0(sun) == 0
    # Saturday
    sat = datetime(2026, 11, 28, 12, 0, tzinfo=HK_TZ)
    assert hk_dow_sunday0(sat) == 6


def test_leave_at_subtracts_travel_and_wait() -> None:
    arrive = datetime(2026, 11, 27, 19, 0, tzinfo=HK_TZ)
    leave = leave_at(arrive=arrive, travel_minutes=25, expected_wait_minutes=40)
    assert leave == datetime(2026, 11, 27, 17, 55, tzinfo=HK_TZ)


def test_parse_arrive_and_resolve_query_local() -> None:
    base = datetime(2026, 11, 27, 12, 0, tzinfo=HK_TZ)
    arrive = parse_arrive_hhmm("19:30", on_date=base)
    assert arrive == datetime(2026, 11, 27, 19, 30, tzinfo=HK_TZ)
    resolved = resolve_query_local(base, arrive_hhmm="19:00")
    assert resolved.hour == 19
    assert hk_dow_sunday0(resolved) == 5
