from app.skills.conflict_detect import detect_conflicts


def _event(
    event_id: str,
    *,
    event_key: str = "车队-抵达-目标区",
    subject: str = "车队",
    action: str = "抵达",
    object_: str = "目标区",
    time_normalized: str | None = None,
    location: str | None = None,
    quantity: dict | None = None,
) -> dict:
    return {
        "event_id": event_id,
        "event_key": event_key,
        "title": "抵达",
        "subject": subject,
        "action": action,
        "object": object_,
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


def test_time_conflict_sides_use_time_field_citations():
    left = _event("EVT-001", time_normalized="2026-06-01T14:00:00")
    right = _event("EVT-002", time_normalized="2026-06-01T16:30:00")
    left["time_citation"] = {"value": "14:00", "evidence_ids": ["E-0101"]}
    right["time_citation"] = {"value": "16:30", "evidence_ids": ["E-0102"]}

    conflicts, warnings = detect_conflicts([left, right], time_conflict_minutes=30)

    assert warnings == []
    assert conflicts[0]["type"] == "time"
    assert conflicts[0]["left"]["evidence_ids"] == ["E-0101"]
    assert conflicts[0]["right"]["evidence_ids"] == ["E-0102"]


def test_does_not_detect_time_conflict_within_threshold():
    conflicts, _ = detect_conflicts(
        [
            _event("EVT-001", time_normalized="2026-06-01T14:00:00"),
            _event("EVT-002", time_normalized="2026-06-01T14:10:00"),
        ],
        time_conflict_minutes=30,
    )

    assert conflicts == []


def test_does_not_detect_time_conflict_at_exact_threshold():
    conflicts, _ = detect_conflicts(
        [
            _event("EVT-001", time_normalized="2026-06-01T14:00:00"),
            _event("EVT-002", time_normalized="2026-06-01T14:30:00"),
        ],
        time_conflict_minutes=30,
    )

    assert conflicts == []


def test_detects_time_conflict_across_midnight_over_threshold():
    conflicts, _ = detect_conflicts(
        [
            _event("EVT-001", time_normalized="2026-06-01T23:50:00"),
            _event("EVT-002", time_normalized="2026-06-02T00:30:00"),
        ],
        time_conflict_minutes=30,
    )

    assert [conflict["type"] for conflict in conflicts] == ["time"]


def test_does_not_detect_time_conflict_across_midnight_at_threshold():
    conflicts, _ = detect_conflicts(
        [
            _event("EVT-001", time_normalized="2026-06-01T23:50:00"),
            _event("EVT-002", time_normalized="2026-06-02T00:20:00"),
        ],
        time_conflict_minutes=30,
    )

    assert conflicts == []


def test_detects_date_conflict_only_when_dates_differ():
    same_day_conflicts, _ = detect_conflicts(
        [
            _event("EVT-001", time_normalized="2026-06-01"),
            _event("EVT-002", time_normalized="2026-06-01"),
        ]
    )
    different_day_conflicts, _ = detect_conflicts(
        [
            _event("EVT-001", time_normalized="2026-06-01"),
            _event("EVT-002", time_normalized="2026-06-02"),
        ]
    )

    assert same_day_conflicts == []
    assert [conflict["type"] for conflict in different_day_conflicts] == ["time"]


def test_does_not_detect_date_vs_same_day_datetime_as_conflict():
    conflicts, _ = detect_conflicts(
        [
            _event("EVT-001", time_normalized="2026-06-01"),
            _event("EVT-002", time_normalized="2026-06-01T16:30:00"),
        ]
    )

    assert conflicts == []


def test_skips_mixed_aware_and_naive_datetimes_with_warning():
    conflicts, warnings = detect_conflicts(
        [
            _event("EVT-001", time_normalized="2026-06-01T14:00:00+08:00"),
            _event("EVT-002", time_normalized="2026-06-01T14:45:00"),
        ],
        time_conflict_minutes=30,
    )

    assert conflicts == []
    assert warnings == ["EVT-001/EVT-002 时间时区信息不一致，未自动判定冲突"]


def test_compares_time_only_values_as_same_day_clock_times():
    conflicts, warnings = detect_conflicts(
        [
            _event("EVT-001", time_normalized="14:00"),
            _event("EVT-002", time_normalized="14:45"),
        ],
        time_conflict_minutes=30,
    )

    assert warnings == []
    assert [conflict["type"] for conflict in conflicts] == ["time"]


def test_detects_location_conflict_for_same_event_key():
    conflicts, _ = detect_conflicts(
        [
            _event("EVT-001", location="地点 A"),
            _event("EVT-002", location="地点 B"),
        ]
    )

    assert [conflict["type"] for conflict in conflicts] == ["location"]


def test_location_conflict_sides_use_location_field_citations():
    left = _event("EVT-001", location="地点 A")
    right = _event("EVT-002", location="地点 B")
    left["location_citation"] = {"value": "地点 A", "evidence_ids": ["E-0201"]}
    right["location_citation"] = {"value": "地点 B", "evidence_ids": ["E-0202"]}

    conflicts, _ = detect_conflicts([left, right])

    assert conflicts[0]["type"] == "location"
    assert conflicts[0]["left"]["evidence_ids"] == ["E-0201"]
    assert conflicts[0]["right"]["evidence_ids"] == ["E-0202"]


def test_does_not_detect_location_conflict_for_same_location_with_spacing():
    conflicts, _ = detect_conflicts(
        [
            _event("EVT-001", location="地点 A"),
            _event("EVT-002", location="地点A"),
        ]
    )

    assert conflicts == []


def test_detects_quantity_conflict_when_units_match_and_values_differ():
    conflicts, _ = detect_conflicts(
        [
            _event("EVT-001", quantity={"value": 3, "unit": "辆"}),
            _event("EVT-002", quantity={"value": 5, "unit": "辆"}),
        ]
    )

    assert [conflict["type"] for conflict in conflicts] == ["quantity"]


def test_quantity_conflict_sides_use_quantity_field_citations():
    left = _event("EVT-001", quantity={"value": 3, "unit": "辆"})
    right = _event("EVT-002", quantity={"value": 5, "unit": "辆"})
    left["quantity_citation"] = {"value": "3辆", "evidence_ids": ["E-0301"]}
    right["quantity_citation"] = {"value": "5辆", "evidence_ids": ["E-0302"]}

    conflicts, _ = detect_conflicts([left, right])

    assert conflicts[0]["type"] == "quantity"
    assert conflicts[0]["left"]["evidence_ids"] == ["E-0301"]
    assert conflicts[0]["right"]["evidence_ids"] == ["E-0302"]


def test_conflict_sides_fall_back_to_event_evidence_without_field_citations():
    conflicts, _ = detect_conflicts(
        [
            _event("EVT-001", quantity={"value": 3, "unit": "辆"}),
            _event("EVT-002", quantity={"value": 5, "unit": "辆"}),
        ]
    )

    assert conflicts[0]["left"]["evidence_ids"] == ["E-0001"]
    assert conflicts[0]["right"]["evidence_ids"] == ["E-0002"]


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
            _event(
                "EVT-002",
                event_key="人员-抵达-目标区",
                subject="人员",
                location="地点 B",
            ),
        ]
    )

    assert conflicts == []


def test_detects_conflict_when_event_keys_drift_but_structured_event_matches():
    conflicts, warnings = detect_conflicts(
        [
            _event(
                "EVT-001",
                event_key="warehouse_activity",
                time_normalized="2026-06-01T14:00:00",
                quantity={"value": 3, "unit": "辆"},
            ),
            _event(
                "EVT-002",
                event_key="east_warehouse_activity",
                time_normalized="2026-06-01T16:00:00",
                quantity={"value": 5, "unit": "辆"},
            ),
            _event(
                "EVT-003",
                event_key="warehouse_vehicle_event",
                time_normalized="2026-06-01T14:10:00",
                quantity={"value": 3, "unit": "辆"},
            ),
        ],
        time_conflict_minutes=30,
    )

    assert warnings == []
    assert {conflict["type"] for conflict in conflicts} == {"time", "quantity"}


def test_does_not_report_location_conflict_for_configured_aliases():
    conflicts, _ = detect_conflicts(
        [
            _event("EVT-001", location="东部仓库"),
            _event("EVT-002", location="东仓"),
        ],
        alias_map={"东仓": "东部仓库"},
    )

    assert conflicts == []


def test_does_not_merge_similar_structured_events_with_different_actions():
    conflicts, _ = detect_conflicts(
        [
            _event(
                "EVT-001",
                event_key="fleet_arrival",
                action="抵达",
                time_normalized="2026-06-01T14:00:00",
            ),
            _event(
                "EVT-002",
                event_key="fleet_not_arrival",
                action="未抵达",
                time_normalized="2026-06-01T16:00:00",
            ),
        ],
        time_conflict_minutes=30,
    )

    assert conflicts == []


def test_does_not_merge_same_object_when_actions_differ():
    conflicts, _ = detect_conflicts(
        [
            _event(
                "EVT-001",
                event_key="load_east_warehouse",
                action="装载",
                object_="东部仓库",
                location="东部仓库",
                quantity={"value": 3, "unit": "辆"},
            ),
            _event(
                "EVT-002",
                event_key="unload_east_warehouse",
                action="卸载",
                object_="东部仓库",
                location="东部仓库",
                quantity={"value": 5, "unit": "辆"},
            ),
        ]
    )

    assert conflicts == []


def test_detects_location_conflict_without_facility_suffix_reduction():
    conflicts, _ = detect_conflicts(
        [
            _event("EVT-001", location="东部仓库"),
            _event("EVT-002", location="东部基地"),
        ]
    )

    assert [conflict["type"] for conflict in conflicts] == ["location"]


def test_preserves_exact_event_key_grouping_when_subjects_differ():
    conflicts, warnings = detect_conflicts(
        [
            _event(
                "EVT-001",
                event_key="shared-checkpoint-event",
                subject="车队",
                time_normalized="2026-06-01T14:00:00",
            ),
            _event(
                "EVT-002",
                event_key="shared-checkpoint-event",
                subject="人员",
                time_normalized="2026-06-01T16:00:00",
            ),
        ],
        time_conflict_minutes=30,
    )

    assert warnings == []
    assert [conflict["type"] for conflict in conflicts] == ["time"]
    assert conflicts[0]["event_key"] == "shared-checkpoint-event"


def test_detects_conflict_for_empty_event_key_when_structured_event_matches():
    conflicts, _ = detect_conflicts(
        [
            _event("EVT-001", event_key="", time_normalized="2026-06-01T14:00:00"),
            _event("EVT-002", event_key="", time_normalized="2026-06-01T16:00:00"),
        ],
        time_conflict_minutes=30,
    )

    assert [conflict["type"] for conflict in conflicts] == ["time"]


def test_empty_unstructured_event_key_warnings_are_aggregated():
    events = [
        _event(
            f"EVT-{index:03d}",
            event_key="",
            subject="",
            action="",
            object_="",
            time_normalized="2026-06-01T14:00:00",
        )
        for index in range(1, 8)
    ]

    conflicts, warnings = detect_conflicts(events)

    assert conflicts == []
    assert warnings == [
        "7 个事件缺少可归一化事件键，未参与冲突比对（示例: EVT-001, EVT-002, EVT-003, EVT-004, EVT-005, ...）"
    ]


def _bare_time_event(event_id: str, time_text: str) -> dict:
    # Real-LLM case: a bare clock time in time_text with no ISO time_normalized.
    return {
        "event_id": event_id,
        "event_key": "delta-check-in-harbor",
        "title": "Delta check-in",
        "subject": "Delta",
        "action": "check-in",
        "object": "Harbor Gate",
        "time_text": time_text,
        "time_normalized": None,
        "location": "Harbor Gate",
        "quantity": None,
        "evidence_ids": [f"E-000{event_id[-1]}"],
        "confidence": 0.9,
    }


def test_detects_time_conflict_from_bare_clock_time_text_without_normalized():
    # Cross-source/cross-modal real-LLM output often leaves time_normalized null
    # and keeps a bare clock time in time_text; conflict detection must still fire.
    conflicts, warnings = detect_conflicts(
        [
            _bare_time_event("EVT-001", "14:00"),
            _bare_time_event("EVT-002", "16:30"),
        ],
        time_conflict_minutes=30,
    )

    assert warnings == []
    assert [conflict["type"] for conflict in conflicts] == ["time"]
    assert {conflicts[0]["left"]["value"], conflicts[0]["right"]["value"]} == {"14:00", "16:30"}


def test_no_time_conflict_for_close_bare_clock_times():
    conflicts, _ = detect_conflicts(
        [
            _bare_time_event("EVT-001", "14:00"),
            _bare_time_event("EVT-002", "14:20"),
        ],
        time_conflict_minutes=30,
    )

    assert conflicts == []
