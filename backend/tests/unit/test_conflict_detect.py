from app.skills.conflict_detect import detect_conflicts


def _event(
    event_id: str,
    *,
    event_key: str = "车队-抵达-目标区",
    time_normalized: str | None = None,
    location: str | None = None,
    quantity: dict | None = None,
) -> dict:
    return {
        "event_id": event_id,
        "event_key": event_key,
        "title": "抵达",
        "subject": "车队",
        "action": "抵达",
        "object": "目标区",
        "time_text": time_normalized,
        "time_normalized": time_normalized,
        "location": location,
        "quantity": quantity,
        "evidence_ids": [f"E-000{event_id[-1]}"],
        "confidence": 0.8,
    }


def test_detects_time_conflict_when_precise_times_differ_by_more_than_threshold():
    conflicts, warnings = detect_conflicts(
        [
            _event("EVT-001", time_normalized="2026-06-01T14:00:00"),
            _event("EVT-002", time_normalized="2026-06-01T16:30:00"),
        ],
        time_conflict_minutes=30,
    )

    assert warnings == []
    assert [conflict["type"] for conflict in conflicts] == ["time"]
    assert conflicts[0]["conflict_id"] == "C-001"


def test_does_not_detect_time_conflict_within_threshold():
    conflicts, _ = detect_conflicts(
        [
            _event("EVT-001", time_normalized="2026-06-01T14:00:00"),
            _event("EVT-002", time_normalized="2026-06-01T14:10:00"),
        ],
        time_conflict_minutes=30,
    )

    assert conflicts == []


def test_detects_location_conflict_for_same_event_key():
    conflicts, _ = detect_conflicts(
        [
            _event("EVT-001", location="地点 A"),
            _event("EVT-002", location="地点 B"),
        ]
    )

    assert [conflict["type"] for conflict in conflicts] == ["location"]


def test_detects_quantity_conflict_when_units_match_and_values_differ():
    conflicts, _ = detect_conflicts(
        [
            _event("EVT-001", quantity={"value": 3, "unit": "辆"}),
            _event("EVT-002", quantity={"value": 5, "unit": "辆"}),
        ]
    )

    assert [conflict["type"] for conflict in conflicts] == ["quantity"]


def test_does_not_compare_quantity_when_units_differ_and_records_warning():
    conflicts, warnings = detect_conflicts(
        [
            _event("EVT-001", quantity={"value": 3, "unit": "辆"}),
            _event("EVT-002", quantity={"value": 3, "unit": "人"}),
        ]
    )

    assert conflicts == []
    assert warnings == ["EVT-001/EVT-002 数量单位不同，未自动判定冲突"]


def test_does_not_compare_events_with_different_event_keys():
    conflicts, _ = detect_conflicts(
        [
            _event("EVT-001", event_key="车队-抵达-目标区", location="地点 A"),
            _event("EVT-002", event_key="人员-抵达-目标区", location="地点 B"),
        ]
    )

    assert conflicts == []
