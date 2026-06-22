import json

from app.skills.base import SkillContext
from app.skills.intelligence_extract import (
    IntelligenceExtractSkill,
    _merge_extractions,
    _sanitize_extraction,
    build_timeline,
)
from app.schemas_analysis import Event, ExtractionResult, FieldCitation


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


def test_sanitize_field_citations_filters_invalid_ids_and_falls_back_to_event_ids():
    raw = {
        "events": [
            {
                "event_key": "车队-发现-车辆",
                "title": "发现车辆",
                "time_text": "6月1日14:00",
                "time_normalized": "2026-06-01T14:00:00",
                "location": "地点A",
                "quantity": {"value": 3, "unit": "辆"},
                "evidence_ids": ["E-0001", "E-0002"],
                "time_citation": {
                    "value": "6月1日14:00",
                    "evidence_ids": ["E-0002", "E-9999", "E-0002"],
                },
                "location_citation": {"value": "地点A", "evidence_ids": ["E-9999"]},
                "quantity_citation": None,
            },
            {
                "event_key": "车队-发现-车辆",
                "title": "发现车辆",
                "location": None,
                "quantity": None,
                "evidence_ids": ["E-0001"],
                "location_citation": {"value": "地点A", "evidence_ids": ["E-0001"]},
                "quantity_citation": {"value": "3辆", "evidence_ids": ["E-0001"]},
            },
        ]
    }

    extraction, warnings = _sanitize_extraction(raw, _evidence())

    assert warnings == []
    event = extraction.events[0]
    assert event.time_citation == FieldCitation(value="6月1日14:00", evidence_ids=["E-0002"])
    assert event.location_citation == FieldCitation(value="地点A", evidence_ids=["E-0001", "E-0002"])
    assert event.quantity_citation == FieldCitation(value="3 辆", evidence_ids=["E-0001", "E-0002"])
    assert extraction.events[1].location_citation is None
    assert extraction.events[1].quantity_citation is None


def test_sanitize_invalid_time_normalized_keeps_time_text_and_warns(tmp_path):
    task_id = "task-invalid-time"
    fixture_dir = tmp_path / "tasks" / task_id / "mock"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "extraction.json").write_text(
        json.dumps(
            {
                "events": [
                    {
                        "event_key": "车队-发现-车辆",
                        "title": "发现车辆",
                        "time_text": "昨日傍晚",
                        "time_normalized": "definitely-not-a-time",
                        "location": "地点A",
                        "evidence_ids": ["E-0001"],
                    }
                ]
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
    assert result.data["events"][0]["time_text"] == "昨日傍晚"
    assert result.data["events"][0]["time_normalized"] is None
    assert result.data["timeline"][0]["time_group"] == "时间未确定"
    assert result.warnings == ["事件时间规范化值不可解析，已置为未确定"]


def test_real_extraction_aggregates_sanitize_warnings(monkeypatch, tmp_path):
    class FakeClient:
        def generate_json(self, _system, _user, _schema):
            return ExtractionResult(
                events=[
                    Event(
                        event_key="车队-发现-车辆",
                        title="发现车辆",
                        evidence_ids=["E-9999"],
                    )
                ]
            )

    monkeypatch.setattr("app.skills.intelligence_extract.settings.mock_ai", False)

    result = IntelligenceExtractSkill(llm_client=FakeClient()).run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "Analyze"}, "evidence": _evidence()},
    )

    assert result.success is True
    assert result.data["events"] == []
    assert result.warnings == [
        "事件结果因缺少有效证据引用已丢弃",
        "真实模型未抽取到任何要素，请检查模型/提示词",
    ]


def test_real_extraction_prompt_includes_schema_example_and_empty_warning(monkeypatch, tmp_path):
    captured: dict[str, str] = {}

    class FakeClient:
        def generate_json(self, system, user, schema):
            captured["system"] = system
            captured["user"] = user
            return schema.model_validate({"entities": [], "events": []})

    monkeypatch.setattr("app.skills.intelligence_extract.settings.mock_ai", False)

    result = IntelligenceExtractSkill(llm_client=FakeClient()).run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "Analyze"}, "evidence": _evidence()},
    )

    assert result.success is True
    assert result.warnings == ["真实模型未抽取到任何要素，请检查模型/提示词"]
    system_prompt = captured["system"]
    user_prompt = captured["user"]
    assert '"entities"' in system_prompt
    assert '"events"' in system_prompt
    assert '"event_key"' in system_prompt
    assert '"quantity": {"value": 3, "unit": "辆"}' in system_prompt
    assert '"time_citation": {"value": "14:00", "evidence_ids": ["E-0003"]}' in system_prompt
    assert '"location_citation"' in system_prompt
    assert '"quantity_citation"' in system_prompt
    assert "直接支持该字段" in system_prompt
    assert "同一真实事件" in system_prompt
    assert "必须取自输入证据中的 [E-xxxx] 编号" in system_prompt
    assert "只输出 JSON" in system_prompt
    assert "[E-0001]" in user_prompt
    assert "[E-0002]" in user_prompt


def test_merge_extractions_combines_evidence_ids_for_same_fact():
    first = ExtractionResult(
        events=[
            Event(
                event_key="车队-发现-车辆",
                title="发现车辆",
                time_normalized="2026-06-01T14:00:00",
                location="地点A",
                evidence_ids=["E-0001"],
                time_citation=FieldCitation(value="14:00", evidence_ids=["E-0001"]),
            )
        ]
    )
    second = ExtractionResult(
        events=[
            Event(
                event_key="车队-发现-车辆",
                title="发现车辆",
                time_normalized="2026-06-01T14:00:00",
                location="地点A",
                evidence_ids=["E-0002", "E-0001"],
                time_citation=FieldCitation(value="14:00", evidence_ids=["E-0002", "E-0001"]),
            )
        ]
    )

    merged = _merge_extractions([first, second])

    assert len(merged.events) == 1
    assert merged.events[0].event_id == "EVT-001"
    assert merged.events[0].evidence_ids == ["E-0001", "E-0002"]
    assert merged.events[0].time_citation == FieldCitation(
        value="14:00",
        evidence_ids=["E-0001", "E-0002"],
    )


def test_build_timeline_carries_time_field_evidence_ids():
    timeline = build_timeline(
        [
            Event(
                event_id="EVT-001",
                event_key="车队-发现-车辆",
                title="发现车辆",
                time_text="14:00",
                time_normalized="2026-06-01T14:00:00",
                evidence_ids=["E-0001"],
                time_citation=FieldCitation(value="14:00", evidence_ids=["E-0002"]),
            )
        ]
    )

    assert timeline[0].evidence_ids == ["E-0001"]
    assert timeline[0].time_evidence_ids == ["E-0002"]
