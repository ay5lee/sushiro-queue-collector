from poller.mapping import extract_called_number, map_queue_metrics, map_store


def test_map_store_basic():
    row = map_store(
        {
            "id": 34,
            "name": "香港仔利港商場店",
            "nameEn": "Aberdeen Port Centre Shopping Arcade",
            "region": "香港島",
            "latitude": 22.25,
            "longitude": 114.15,
            "address": "somewhere",
            "wait": 12,
            "waitingGroup": 3,
            "storeStatus": "OPEN",
        }
    )
    assert row.store_id == "34"
    assert row.name_zh.startswith("香港仔")
    assert row.wait_minutes == 12
    assert row.waiting_group == 3


def test_called_number_walkin_only():
    payload = {
        "storeQueue": ["74", "73-1"],
        "boothQueue": ["#70"],
        "reservationQueue": ["8220", "8211"],
        "counterQueue": [],
        "mixedQueue": [],
    }
    assert extract_called_number(payload) == 74


def test_queue_number_derived():
    metrics = map_queue_metrics(
        wait_minutes=20,
        waiting_group=5,
        groupqueues={"storeQueue": ["100"], "boothQueue": [], "counterQueue": []},
    )
    assert metrics.called_number == 100
    assert metrics.queue_number == 105
    assert metrics.wait_minutes == 20
