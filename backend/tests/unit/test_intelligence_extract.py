import json

from app.skills.base import SkillContext
from app.skills.intelligence_extract import IntelligenceExtractSkill


def _context(tmp_path, task_id: str = "task-1") -> SkillContext:
    return SkillContext(task_id=task_id, run_id="run-1", data_root=str(tmp_path))


def _evidence() -> list[dict]:
    return [
        {
            "display_id": "E-0001",
            "content": "6月1日14:00，车队在地点A发现3辆车。",
            "content_summary": "6月1日14:00，车队在地点A发现3辆车。",
            "file": {"original_name": "a.txt"},
            "locator": {"kind": "text", "paragraph": 1},
        },
        {
            "display_id": "E-0002",
            "content": "6月1日16:30，车队在地点B发现5辆车。",
            "content_summary": "6月1日16:30，车队在地点B发现5辆车。",
            "file": {"original_name": "b.txt"},
            "locator": {"kind": "text", "paragraph": 1},
        },
    ]


def test_default_mock_extraction_uses_real_evidence_ids_and_sorted_timeline(tmp_path):
    result = IntelligenceExtractSkill().run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "Analyze"}, "evidence": _evidence()},
    )

    assert result.success is True
    events = result.data["events"]
    timeline = result.data["timeline"]
    assert {evidence_id for event in events for evidence_id in event["evidence_ids"]} <= {"E-0001", "E-0002"}
    assert [event["event_id"] for event in events] == ["EVT-001", "EVT-002"]
    assert [item["time_normalized"] for item in timeline[:2]] == [
        "2026-06-01T14:00:00",
        "2026-06-01T16:30:00",
    ]


def test_default_mock_extraction_keeps_conflicting_events_with_single_evidence(tmp_path):
    [single_evidence, *_] = _evidence()

    result = IntelligenceExtractSkill().run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "Analyze"}, "evidence": [single_evidence]},
    )

    assert result.success is True
    assert len(result.data["events"]) == 2
    assert {event["event_key"] for event in result.data["events"]} == {"车队-发现-车辆"}
    assert {event["evidence_ids"][0] for event in result.data["events"]} == {"E-0001"}


def test_extraction_fails_clearly_when_evidence_is_empty(tmp_path):
    result = IntelligenceExtractSkill().run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "Analyze"}, "evidence": []},
    )

    assert result.success is False
    assert result.errors == ["没有可用于要素提取的证据"]


def test_task_fixture_can_resolve_match_to_display_id_and_ignore_extra_fields(tmp_path):
    task_id = "task-fixture"
    fixture_dir = tmp_path / "tasks" / task_id / "mock"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "extraction.json").write_text(
        json.dumps(
            {
                "entities": [
                    {
                        "type": "location",
                        "name": "地点A",
                        "evidence_ids": ["E-9999"],
                        "match": "地点A",
                        "extra_field": "ignored",
                    }
                ],
                "events": [
                    {
                        "event_key": "车队-发现-车辆",
                        "title": "发现车辆",
                        "subject": "车队",
                        "action": "发现",
                        "object": "车辆",
                        "time_text": "6月1日14:00",
                        "time_normalized": "2026-06-01T14:00:00",
                        "location": "地点A",
                        "quantity": {"value": 3, "unit": "辆"},
                        "evidence_ids": ["E-9999"],
                        "match": "地点A",
                        "confidence": 0.8,
                        "extra_field": "ignored",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = IntelligenceExtractSkill().run(
        _context(tmp_path, task_id),
        {"task": {"name": "Case", "objective": "Analyze"}, "evidence": _evidence()},
    )

    assert result.success is True
    assert result.data["entities"][0]["evidence_ids"] == ["E-0001"]
    assert result.data["events"][0]["evidence_ids"] == ["E-0001"]
    assert "extra_field" not in result.data["events"][0]
