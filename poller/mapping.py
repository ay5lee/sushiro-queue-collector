from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# Walk-in queue arrays on groupqueues. Reservation queues are excluded when
# deriving called_number (base >= 1000 is treated as reservation elsewhere).
WALKIN_QUEUE_KEYS = (
    "storeQueue",
    "boothQueue",
    "counterQueue",
    "mixedQueue",
    "storeCounterQueue",
    "storeBoothQueue",
)

ALL_QUEUE_KEYS = WALKIN_QUEUE_KEYS + (
    "reservationQueue",
    "reservationCounterQueue",
    "reservationBoothQueue",
)


@dataclass(frozen=True)
class StoreRow:
    store_id: str
    name_en: str | None
    name_zh: str | None
    region: str | None
    latitude: float | None
    longitude: float | None
    address: str | None
    wait_minutes: int | None
    waiting_group: int | None
    store_status: str | None
    raw_json: dict[str, Any]


@dataclass(frozen=True)
class QueueMetrics:
    wait_minutes: int | None
    queue_number: int | None
    called_number: int | None
    group_key: str | None
    waiting_group: int | None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            return None
    return number


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_ticket_base(raw: Any) -> int | None:
    """Parse ticket strings like '74', '74-1', '#8220' → base integer."""
    if raw is None:
        return None
    text = str(raw).strip().lstrip("#")
    if not text:
        return None
    base = text.split("-", 1)[0]
    return _as_int(base)


def map_store(payload: dict[str, Any]) -> StoreRow:
    store_id = str(payload.get("id"))
    wait = _as_int(payload.get("wait"))
    # API sometimes returns -1 for unused counter wait fields; keep wait as-is
    # when non-negative, else null.
    if wait is not None and wait < 0:
        wait = None
    return StoreRow(
        store_id=store_id,
        name_en=(payload.get("nameEn") or None),
        name_zh=(payload.get("name") or None),
        region=(payload.get("region") or payload.get("area") or None),
        latitude=_as_float(payload.get("latitude")),
        longitude=_as_float(payload.get("longitude")),
        address=(payload.get("address") or None),
        wait_minutes=wait,
        waiting_group=_as_int(payload.get("waitingGroup")),
        store_status=(payload.get("storeStatus") or None),
        raw_json=payload,
    )


def extract_called_number(groupqueues: dict[str, Any]) -> int | None:
    """Max walk-in called ticket base from groupqueues arrays.

    Matching scmlewis/sushiro-hk-live notify-logic: walk-in bases are < 1000;
    reservation tickets use larger bases and are ignored for called_number.
    """
    bases: list[int] = []
    for key in WALKIN_QUEUE_KEYS:
        values = groupqueues.get(key) or []
        if not isinstance(values, list):
            continue
        for item in values:
            base = parse_ticket_base(item)
            if base is None:
                continue
            if base >= 1000:
                continue
            bases.append(base)
    if not bases:
        return None
    return max(bases)


def map_queue_metrics(
    *,
    wait_minutes: int | None,
    waiting_group: int | None,
    groupqueues: dict[str, Any],
) -> QueueMetrics:
    called = extract_called_number(groupqueues)

    # Last issued ticket is not exposed as its own field on either endpoint.
    # Approximate as called + groups waiting when both are known.
    queue_number: int | None = None
    if called is not None and waiting_group is not None and waiting_group >= 0:
        queue_number = called + waiting_group

    return QueueMetrics(
        wait_minutes=wait_minutes,
        queue_number=queue_number,
        called_number=called,
        group_key="walkin",
        waiting_group=waiting_group,
    )


def normalize_storelist(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("stores", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []
