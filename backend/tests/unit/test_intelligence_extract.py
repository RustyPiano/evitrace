import json
import re
import threading
import time

import pytest
from fastapi import status

from app.schemas import AppError
from app.skills.base import RunCancelled
from app.skills.base import SkillContext
from app.skills.intelligence_extract import (
    IntelligenceExtractSkill,
    _batch_evidence,
    _merge_extractions,
    _prefilter_evidence,
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


def _many_evidence(count: int) -> list[dict]:
    return [
        {
            "display_id": f"E-{index + 1:04d}",
            "content": f"6月1日14:00，分队在地点{index + 1}发现{index + 1}辆车。",
            "content_summary": f"6月1日14:00，分队在地点{index + 1}发现{index + 1}辆车。",
            "file": {"original_name": f"{index + 1}.txt"},
            "locator": {"kind": "text", "paragraph": index + 1},
        }
        for index in range(count)
    ]


class FakePersistence:
    def __init__(self, done: dict[int, tuple[str, dict]] | None = None) -> None:
        self.done = done or {}
        self.records: list[tuple[int, str, str, dict | None, str | None, str | None, str]] = []
        self.plan: tuple[int, int] | None = None
        self.thread_name = threading.current_thread().name

    def load_done(self) -> dict[int, tuple[str, dict]]:
        assert threading.current_thread().name == self.thread_name
        return dict(self.done)

    def record_batch(
        self,
        batch_index: int,
        input_hash: str,
        status: str,
        result: dict | None,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        assert threading.current_thread().name == self.thread_name
        self.records.append((batch_index, input_hash, status, result, error_code, error_message, threading.current_thread().name))
        if status == "done" and result is not None:
            self.done[batch_index] = (input_hash, result)

    def set_plan(self, total_batches: int, estimated_input_tokens: int) -> None:
        assert threading.current_thread().name == self.thread_name
        self.plan = (total_batches, estimated_input_tokens)


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


def test_prefilter_evidence_drops_blank_short_and_duplicate_while_preserving_order():
    evidence = [
        {"display_id": "E-0001", "content": "  Alpha  "},
        {"display_id": "E-0002", "content": "   "},
        {"display_id": "E-0003", "content": "alpha"},
        {"display_id": "E-0004", "content": "ab"},
        {"display_id": "E-0005", "content": "Beta"},
    ]

    kept, stats = _prefilter_evidence(evidence, min_chars=3)

    assert [item["display_id"] for item in kept] == ["E-0001", "E-0005"]
    assert stats == {
        "original": 5,
        "kept": 2,
        "dropped_duplicate": 1,
        "dropped_low_signal": 2,
    }


def test_batch_evidence_uses_explicit_or_configured_limits(monkeypatch):
    evidence = _many_evidence(5)

    assert [len(batch) for batch in _batch_evidence(evidence, max_items=2, max_chars=12000)] == [2, 2, 1]

    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_batch_max_items", 3, raising=False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_batch_max_chars", 12000, raising=False)

    assert [len(batch) for batch in _batch_evidence(evidence)] == [3, 2]
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_batch_max_items", 30, raising=False)
    assert [len(batch) for batch in _batch_evidence(_many_evidence(31))] == [30, 1]


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
    assert event.time_citation == FieldCitation(
        value="6月1日14:00",
        evidence_ids=["E-0002"],
        citation_origin="explicit",
    )
    assert event.location_citation == FieldCitation(
        value="地点A",
        evidence_ids=["E-0001", "E-0002"],
        citation_origin="fallback",
    )
    assert event.quantity_citation == FieldCitation(
        value="3 辆",
        evidence_ids=["E-0001", "E-0002"],
        citation_origin="fallback",
    )
    assert extraction.events[1].location_citation is None
    assert extraction.events[1].quantity_citation is None


def test_sanitize_field_citations_ignore_model_value_and_mark_origin():
    raw = {
        "events": [
            {
                "event_key": "车队-发现-车辆",
                "title": "发现车辆",
                "time_text": "6月1日14:00",
                "location": "地点A",
                "quantity": {"value": 3, "unit": "辆"},
                "evidence_ids": ["E-0001"],
                "time_citation": {"value": "6月1日16:30", "evidence_ids": ["E-0002"]},
                "location_citation": {"value": "地点B", "evidence_ids": []},
                "quantity_citation": {"value": "5辆", "evidence_ids": ["E-9999"]},
            }
        ]
    }

    extraction, warnings = _sanitize_extraction(raw, _evidence())

    assert warnings == []
    event = extraction.events[0]
    assert event.time_citation == FieldCitation(
        value="6月1日14:00",
        evidence_ids=["E-0002"],
        citation_origin="explicit",
    )
    assert event.location_citation == FieldCitation(
        value="地点A",
        evidence_ids=["E-0001"],
        citation_origin="fallback",
    )
    assert event.quantity_citation == FieldCitation(
        value="3 辆",
        evidence_ids=["E-0001"],
        citation_origin="fallback",
    )


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


def test_real_extraction_prefilters_before_batching_and_discloses_savings(monkeypatch, tmp_path):
    calls: list[str] = []

    class FakeClient:
        def generate_json(self, _system, user, schema):
            calls.append(user)
            display_ids = re.findall(r"\[(E-\d{4})\]", user)
            return schema.model_validate(
                {
                    "events": [
                        {
                            "event_key": f"分队-发现-{display_ids[0]}",
                            "title": "发现车辆",
                            "evidence_ids": [display_ids[0]],
                        }
                    ]
                }
            )

    evidence = [
        {
            "display_id": "E-0001",
            "content": "Alpha target",
            "content_summary": "Alpha target",
            "file": {"original_name": "a.txt"},
            "locator": {"kind": "text"},
        },
        {
            "display_id": "E-0002",
            "content": " alpha target ",
            "content_summary": " alpha target ",
            "file": {"original_name": "b.txt"},
            "locator": {"kind": "text"},
        },
        {
            "display_id": "E-0003",
            "content": "  ",
            "content_summary": "  ",
            "file": {"original_name": "c.txt"},
            "locator": {"kind": "text"},
        },
        {
            "display_id": "E-0004",
            "content": "Beta target",
            "content_summary": "Beta target",
            "file": {"original_name": "d.txt"},
            "locator": {"kind": "text"},
        },
    ]
    monkeypatch.setattr("app.skills.intelligence_extract.settings.mock_ai", False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_min_evidence_chars", 0, raising=False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_batch_max_items", 1, raising=False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_batch_max_chars", 12000, raising=False)

    result = IntelligenceExtractSkill(llm_client=FakeClient()).run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "Analyze"}, "evidence": evidence},
    )

    assert result.success is True
    assert len(calls) == 2
    assert "[E-0001]" in calls[0]
    assert "[E-0004]" in calls[1]
    assert "[E-0002]" not in "\n".join(calls)
    assert result.data["events"][0]["evidence_ids"] == ["E-0001"]
    assert result.warnings == [
        "为节省真实模型调用，已跳过 1 条重复证据、1 条空白/过短证据（原 4 条 → 实际抽取 2 条）"
    ]


def test_real_extraction_relevance_prefilter_sends_only_selected_evidence_and_warns(monkeypatch, tmp_path):
    calls: list[str] = []

    class FakeClient:
        def generate_json(self, _system, user, schema):
            calls.append(user)
            display_ids = re.findall(r"\[(E-\d{4})\]", user)
            return schema.model_validate(
                {
                    "events": [
                        {
                            "event_key": f"分队-发现-{display_id}",
                            "title": "发现车辆",
                            "evidence_ids": [display_id],
                        }
                        for display_id in display_ids
                    ]
                }
            )

    evidence = [
        {
            "display_id": "E-0001",
            "content": "目标车队在A镇发现3辆车。",
            "content_summary": "目标车队在A镇发现3辆车。",
            "file": {"id": "doc-a", "original_name": "a.txt"},
            "locator": {"kind": "text"},
        },
        {
            "display_id": "E-0002",
            "content": "普通巡逻完成。",
            "content_summary": "普通巡逻完成。",
            "file": {"id": "doc-a", "original_name": "a.txt"},
            "locator": {"kind": "text"},
        },
        {
            "display_id": "E-0003",
            "content": "目标车队在B镇发现5辆车。",
            "content_summary": "目标车队在B镇发现5辆车。",
            "file": {"id": "doc-b", "original_name": "b.txt"},
            "locator": {"kind": "text"},
        },
        {
            "display_id": "E-0004",
            "content": "天气晴朗，道路通畅。",
            "content_summary": "天气晴朗，道路通畅。",
            "file": {"id": "doc-b", "original_name": "b.txt"},
            "locator": {"kind": "text"},
        },
    ]
    monkeypatch.setattr("app.skills.intelligence_extract.settings.mock_ai", False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_relevance_top_k", 2, raising=False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_relevance_per_doc_min", 1, raising=False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_batch_max_items", 30, raising=False)

    result = IntelligenceExtractSkill(llm_client=FakeClient()).run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "目标车队 A镇 B镇"}, "evidence": evidence},
    )

    sent = "\n".join(calls)
    assert result.success is True
    assert len(calls) == 1
    assert "[E-0001]" in sent
    assert "[E-0002]" not in sent
    assert "[E-0003]" in sent
    assert "[E-0004]" not in sent
    assert [event["evidence_ids"][0] for event in result.data["events"]] == ["E-0001", "E-0003"]
    assert result.warnings == [
        "已按相关性预筛：从 4 条相关排序保留 2 条（每文档≥1，top_k=2），"
        "其余 2 条未进入本次分析；如需全量请调大或关闭 EXTRACT_RELEVANCE_TOP_K"
    ]


def test_real_extraction_relevance_prefilter_noops_when_disabled_or_not_smaller(monkeypatch, tmp_path):
    calls: list[str] = []

    class FakeClient:
        def generate_json(self, _system, user, schema):
            calls.append(user)
            display_ids = re.findall(r"\[(E-\d{4})\]", user)
            return schema.model_validate(
                {
                    "events": [
                        {
                            "event_key": f"分队-发现-{display_id}",
                            "title": "发现车辆",
                            "evidence_ids": [display_id],
                        }
                        for display_id in display_ids
                    ]
                }
            )

    monkeypatch.setattr("app.skills.intelligence_extract.settings.mock_ai", False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_batch_max_items", 30, raising=False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_relevance_per_doc_min", 0, raising=False)

    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_relevance_top_k", 0, raising=False)
    disabled = IntelligenceExtractSkill(llm_client=FakeClient()).run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "地点1"}, "evidence": _many_evidence(3)},
    )

    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_relevance_top_k", 3, raising=False)
    not_smaller = IntelligenceExtractSkill(llm_client=FakeClient()).run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "地点1"}, "evidence": _many_evidence(3)},
    )

    assert disabled.success is True
    assert not_smaller.success is True
    assert len(calls) == 2
    assert all(display_id in calls[0] for display_id in ("[E-0001]", "[E-0002]", "[E-0003]"))
    assert all(display_id in calls[1] for display_id in ("[E-0001]", "[E-0002]", "[E-0003]"))
    assert disabled.warnings == []
    assert not_smaller.warnings == []


def test_real_extraction_prefilter_warning_and_relevance_warning_can_coexist(monkeypatch, tmp_path):
    calls: list[str] = []

    class FakeClient:
        def generate_json(self, _system, user, schema):
            calls.append(user)
            display_id = re.search(r"\[(E-\d{4})\]", user).group(1)
            return schema.model_validate(
                {
                    "events": [
                        {
                            "event_key": f"分队-发现-{display_id}",
                            "title": "发现车辆",
                            "evidence_ids": [display_id],
                        }
                    ]
                }
            )

    evidence = [
        {
            "display_id": "E-0001",
            "content": "目标车队在A镇发现3辆车。",
            "content_summary": "目标车队在A镇发现3辆车。",
            "file": {"id": "doc-a", "original_name": "a.txt"},
            "locator": {"kind": "text"},
        },
        {
            "display_id": "E-0002",
            "content": " 目标车队在A镇发现3辆车。 ",
            "content_summary": " 目标车队在A镇发现3辆车。 ",
            "file": {"id": "doc-a", "original_name": "a.txt"},
            "locator": {"kind": "text"},
        },
        {
            "display_id": "E-0003",
            "content": "天气晴朗，道路通畅。",
            "content_summary": "天气晴朗，道路通畅。",
            "file": {"id": "doc-b", "original_name": "b.txt"},
            "locator": {"kind": "text"},
        },
    ]
    monkeypatch.setattr("app.skills.intelligence_extract.settings.mock_ai", False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_relevance_top_k", 1, raising=False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_relevance_per_doc_min", 0, raising=False)

    result = IntelligenceExtractSkill(llm_client=FakeClient()).run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "目标车队 A镇"}, "evidence": evidence},
    )

    assert result.success is True
    assert len(calls) == 1
    assert "[E-0001]" in calls[0]
    assert "[E-0002]" not in calls[0]
    assert "[E-0003]" not in calls[0]
    assert result.warnings == [
        "为节省真实模型调用，已跳过 1 条重复证据、0 条空白/过短证据（原 3 条 → 实际抽取 2 条）",
        "已按相关性预筛：从 2 条相关排序保留 1 条（每文档≥0，top_k=1），"
        "其余 1 条未进入本次分析；如需全量请调大或关闭 EXTRACT_RELEVANCE_TOP_K",
    ]


def test_mock_extraction_does_not_prefilter_duplicate_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_min_evidence_chars", 100, raising=False)
    evidence = [
        {
            "display_id": "E-0001",
            "content": "same",
            "content_summary": "same",
            "file": {"original_name": "a.txt"},
            "locator": {"kind": "text"},
        },
        {
            "display_id": "E-0002",
            "content": "same",
            "content_summary": "same",
            "file": {"original_name": "b.txt"},
            "locator": {"kind": "text"},
        },
    ]

    result = IntelligenceExtractSkill().run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "Analyze"}, "evidence": evidence},
    )

    assert result.success is True
    assert {event["evidence_ids"][0] for event in result.data["events"]} == {"E-0001", "E-0002"}
    assert result.warnings == []


def test_real_extraction_runs_batches_concurrently_and_reports_progress(monkeypatch, tmp_path):
    active = 0
    max_active = 0
    lock = threading.Lock()

    class FakeClient:
        def generate_json(self, _system, user, schema):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.03)
            with lock:
                active -= 1
            display_id = re.search(r"\[(E-\d{4})\]", user).group(1)
            return schema.model_validate(
                {
                    "entities": [
                        {
                            "type": "location",
                            "name": f"地点{display_id}",
                            "confidence": 0.8,
                            "evidence_ids": [display_id],
                        }
                    ],
                    "events": [
                        {
                            "event_key": f"分队-发现-{display_id}",
                            "title": "发现车辆",
                            "time_text": "6月1日14:00",
                            "location": f"地点{display_id}",
                            "evidence_ids": [display_id],
                            "confidence": 0.8,
                        }
                    ],
                }
            )

    progress: list[tuple[int, int, int]] = []
    monkeypatch.setattr("app.skills.intelligence_extract.settings.mock_ai", False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_concurrency", 3, raising=False)

    result = IntelligenceExtractSkill(llm_client=FakeClient()).run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "Analyze"}, "evidence": _many_evidence(95)},
        progress_callback=lambda done, failed, total: progress.append((done, failed, total)),
    )

    assert result.success is True
    assert len(result.data["events"]) == 4
    assert max_active > 1
    assert progress == [(1, 0, 4), (2, 0, 4), (3, 0, 4), (4, 0, 4)]


def test_real_extraction_keeps_batch_order_when_batches_finish_out_of_order(monkeypatch, tmp_path):
    class FakeClient:
        def generate_json(self, _system, user, schema):
            display_id = re.search(r"\[(E-\d{4})\]", user).group(1)
            if display_id == "E-0001":
                time.sleep(0.04)
            return schema.model_validate(
                {
                    "events": [
                        {
                            "event_key": f"分队-发现-{display_id}",
                            "title": f"发现{display_id}",
                            "time_text": "6月1日14:00",
                            "location": f"地点{display_id}",
                            "evidence_ids": [display_id],
                            "confidence": 0.8,
                        }
                    ]
                }
            )

    monkeypatch.setattr("app.skills.intelligence_extract.settings.mock_ai", False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_concurrency", 2, raising=False)

    result = IntelligenceExtractSkill(llm_client=FakeClient()).run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "Analyze"}, "evidence": _many_evidence(95)},
    )

    assert result.success is True
    assert [event["event_id"] for event in result.data["events"]] == [
        "EVT-001",
        "EVT-002",
        "EVT-003",
        "EVT-004",
    ]
    assert [event["evidence_ids"][0] for event in result.data["events"]] == [
        "E-0001",
        "E-0031",
        "E-0061",
        "E-0091",
    ]


def test_real_extraction_cancels_pending_batches_and_propagates_run_cancelled(monkeypatch, tmp_path):
    call_count = 0

    class FakeClient:
        def generate_json(self, _system, user, schema):
            nonlocal call_count
            call_count += 1
            display_id = re.search(r"\[(E-\d{4})\]", user).group(1)
            if display_id != "E-0001":
                time.sleep(0.05)
            return schema.model_validate(
                {
                    "events": [
                        {
                            "event_key": f"分队-发现-{display_id}",
                            "title": "发现车辆",
                            "evidence_ids": [display_id],
                        }
                    ]
                }
            )

    progress: list[tuple[int, int, int]] = []
    monkeypatch.setattr("app.skills.intelligence_extract.settings.mock_ai", False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_concurrency", 2, raising=False)

    with pytest.raises(RunCancelled):
        IntelligenceExtractSkill(llm_client=FakeClient()).run(
            _context(tmp_path),
            {"task": {"name": "Case", "objective": "Analyze"}, "evidence": _many_evidence(95)},
            progress_callback=lambda done, failed, total: progress.append((done, failed, total)),
            cancel_check=lambda: len(progress) >= 1,
        )

    assert progress == [(1, 0, 4)]
    assert call_count <= progress[-1][0] + 2


def test_real_extraction_progress_advances_for_success_and_failed_batches(monkeypatch, tmp_path):
    class FakeClient:
        def generate_json(self, _system, user, schema):
            display_id = re.search(r"\[(E-\d{4})\]", user).group(1)
            if display_id == "E-0002":
                raise RuntimeError("boom")
            return schema.model_validate(
                {
                    "events": [
                        {
                            "event_key": f"分队-发现-{display_id}",
                            "title": "发现车辆",
                            "evidence_ids": [display_id],
                        }
                    ]
                }
            )

    progress: list[tuple[int, int, int]] = []
    monkeypatch.setattr("app.skills.intelligence_extract.settings.mock_ai", False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_batch_max_items", 1, raising=False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_concurrency", 1, raising=False)

    result = IntelligenceExtractSkill(llm_client=FakeClient()).run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "Analyze"}, "evidence": _evidence()},
        progress_callback=lambda done, failed, total: progress.append((done, failed, total)),
    )

    assert result.success is True
    assert progress == [(1, 0, 2), (1, 1, 2)]
    assert progress[-1][0] + progress[-1][1] == progress[-1][2]
    assert result.metrics["batch_done"] == 1
    assert result.metrics["batch_failed"] == 1


def test_real_extraction_prefilled_done_batches_report_progress_with_failed_zero(monkeypatch, tmp_path):
    progress: list[tuple[int, int, int]] = []

    monkeypatch.setattr("app.skills.intelligence_extract.settings.mock_ai", False)
    persistence = FakePersistence()

    class FakeClient:
        def generate_json(self, _system, user, schema):
            display_id = re.search(r"\[(E-\d{4})\]", user).group(1)
            return schema.model_validate({"events": [{"event_key": display_id, "title": display_id, "evidence_ids": [display_id]}]})

    skill = IntelligenceExtractSkill(llm_client=FakeClient())
    first = skill.run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "Analyze"}, "evidence": _evidence()[:1]},
        persistence=persistence,
    )
    assert first.success is True

    result = skill.run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "Analyze"}, "evidence": _evidence()[:1]},
        persistence=persistence,
        progress_callback=lambda done, failed, total: progress.append((done, failed, total)),
    )

    assert result.success is True
    assert progress == [(1, 0, 1)]


def test_real_extraction_global_rate_limit_cooldown_delays_new_submissions(monkeypatch, tmp_path):
    submit_times: list[float] = []
    now = 0.0

    def monotonic_fn() -> float:
        return now

    def sleep_fn(seconds: float) -> None:
        nonlocal now
        now += seconds

    class FakeClient:
        def generate_json(self, _system, user, schema):
            display_id = re.search(r"\[(E-\d{4})\]", user).group(1)
            submit_times.append(monotonic_fn())
            if display_id == "E-0001":
                exc = AppError("LLM_RATE_LIMITED", "too many requests", status.HTTP_429_TOO_MANY_REQUESTS)
                exc.retry_after = 2.0
                raise exc
            return schema.model_validate(
                {"events": [{"event_key": display_id, "title": display_id, "evidence_ids": [display_id]}]}
            )

    monkeypatch.setattr("app.skills.intelligence_extract.settings.mock_ai", False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_batch_max_items", 1, raising=False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_concurrency", 1, raising=False)

    _merged, _warnings, stats = IntelligenceExtractSkill(llm_client=FakeClient())._run_real_extraction(
        {"task": {"name": "Case", "objective": "Analyze"}},
        _evidence(),
        sleep_fn=sleep_fn,
        monotonic_fn=monotonic_fn,
    )

    assert stats == {"total": 2, "done": 1, "failed": 1, "aborted": False}
    assert submit_times == [0.0, 2.0]


def test_real_extraction_rate_limit_circuit_breaker_stops_unsubmitted_batches(monkeypatch, tmp_path):
    call_count = 0

    class FakeClient:
        def generate_json(self, _system, _user, _schema):
            nonlocal call_count
            call_count += 1
            raise AppError("LLM_RATE_LIMITED", "too many requests", status.HTTP_429_TOO_MANY_REQUESTS)

    monkeypatch.setattr("app.skills.intelligence_extract.settings.mock_ai", False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_batch_max_items", 1, raising=False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_concurrency", 1, raising=False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_rate_limit_circuit_breaker", 2, raising=False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_rate_limit_cooldown_sec", 0, raising=False)

    result = IntelligenceExtractSkill(llm_client=FakeClient()).run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "Analyze"}, "evidence": _many_evidence(5)},
    )

    assert result.success is True
    assert call_count == 2
    assert result.metrics["batch_total"] == 5
    assert result.metrics["batch_done"] == 0
    assert result.metrics["batch_failed"] == 2
    assert result.metrics["batch_aborted"] is True
    assert result.metrics["batch_done"] + result.metrics["batch_failed"] < result.metrics["batch_total"]
    assert any("上游持续限流，已停止提交剩余批次" in warning for warning in result.warnings)


def test_real_extraction_cancel_check_runs_during_rate_limit_cooldown(monkeypatch, tmp_path):
    now = 0.0
    sleep_calls = 0

    def monotonic_fn() -> float:
        return now

    def sleep_fn(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1

    def cancel_check() -> bool:
        return sleep_calls >= 1

    class FakeClient:
        def generate_json(self, _system, _user, _schema):
            exc = AppError("LLM_RATE_LIMITED", "too many requests", status.HTTP_429_TOO_MANY_REQUESTS)
            exc.retry_after = 2.0
            raise exc

    monkeypatch.setattr("app.skills.intelligence_extract.settings.mock_ai", False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_batch_max_items", 1, raising=False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_concurrency", 1, raising=False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_rate_limit_circuit_breaker", 0, raising=False)

    with pytest.raises(RunCancelled):
        IntelligenceExtractSkill(llm_client=FakeClient())._run_real_extraction(
            {"task": {"name": "Case", "objective": "Analyze"}},
            _evidence(),
            cancel_check=cancel_check,
            sleep_fn=sleep_fn,
            monotonic_fn=monotonic_fn,
        )


def test_real_extraction_persists_partial_results_and_resumes_only_failed_batch(monkeypatch, tmp_path):
    calls: list[str] = []

    class FakeClient:
        def __init__(self, fail: bool) -> None:
            self.fail = fail

        def generate_json(self, _system, user, schema):
            display_id = re.search(r"\[(E-\d{4})\]", user).group(1)
            calls.append(display_id)
            if self.fail and display_id == "E-0031":
                raise AppError("LLM_RATE_LIMITED", "too many requests", status.HTTP_429_TOO_MANY_REQUESTS)
            return schema.model_validate(
                {
                    "events": [
                        {
                            "event_key": f"分队-发现-{display_id}",
                            "title": f"发现{display_id}",
                            "time_text": "6月1日14:00",
                            "location": f"地点{display_id}",
                            "evidence_ids": [display_id],
                            "confidence": 0.8,
                        }
                    ]
                }
            )

    monkeypatch.setattr("app.skills.intelligence_extract.settings.mock_ai", False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_concurrency", 2, raising=False)
    persistence = FakePersistence()

    first = IntelligenceExtractSkill(llm_client=FakeClient(fail=True)).run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "Analyze"}, "evidence": _many_evidence(95)},
        persistence=persistence,
    )

    assert first.success is True
    assert first.metrics["batch_total"] == 4
    assert first.metrics["batch_done"] == 3
    assert first.metrics["batch_failed"] == 1
    # 并发下批次按完成顺序记录，故按 status 过滤而非依赖位置（records[1] 是时序相关的）。
    failed_records = [record for record in persistence.records if record[2] == "failed"]
    assert [record[0] for record in failed_records] == [1]
    assert failed_records[0][4] == "LLM_RATE_LIMITED"
    assert "部分抽取失败：3/4 批成功、1 批失败" in first.warnings[-1]
    assert [event["event_id"] for event in first.data["events"]] == ["EVT-001", "EVT-002", "EVT-003"]

    calls.clear()
    persistence.records.clear()
    second = IntelligenceExtractSkill(llm_client=FakeClient(fail=False)).run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "Analyze"}, "evidence": _many_evidence(95)},
        persistence=persistence,
    )

    assert second.success is True
    assert calls == ["E-0031"]
    assert second.metrics["batch_total"] == 4
    assert second.metrics["batch_done"] == 4
    assert second.metrics["batch_failed"] == 0
    assert [event["event_id"] for event in second.data["events"]] == [
        "EVT-001",
        "EVT-002",
        "EVT-003",
        "EVT-004",
    ]
    assert [event["evidence_ids"][0] for event in second.data["events"]] == [
        "E-0001",
        "E-0031",
        "E-0061",
        "E-0091",
    ]


def test_real_extraction_ignores_done_cache_when_input_hash_mismatches(monkeypatch, tmp_path):
    calls: list[str] = []
    stale = ExtractionResult(
        events=[Event(event_key="stale", title="stale", evidence_ids=["E-0001"])]
    ).model_dump(mode="json")
    persistence = FakePersistence(done={0: ("stale-hash", stale)})

    class FakeClient:
        def generate_json(self, _system, user, schema):
            display_id = re.search(r"\[(E-\d{4})\]", user).group(1)
            calls.append(display_id)
            return schema.model_validate(
                {
                    "events": [
                        {
                            "event_key": f"fresh-{display_id}",
                            "title": "fresh",
                            "evidence_ids": [display_id],
                        }
                    ]
                }
            )

    monkeypatch.setattr("app.skills.intelligence_extract.settings.mock_ai", False)

    result = IntelligenceExtractSkill(llm_client=FakeClient()).run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "Analyze"}, "evidence": _evidence()},
        persistence=persistence,
    )

    assert result.success is True
    assert calls == ["E-0001"]
    assert result.data["events"][0]["event_key"] == "fresh-E-0001"


def test_real_extraction_objective_change_invalidates_done_cache(monkeypatch, tmp_path):
    calls: list[str] = []

    class FakeClient:
        def generate_json(self, _system, user, schema):
            display_id = re.search(r"\[(E-\d{4})\]", user).group(1)
            calls.append(display_id)
            return schema.model_validate(
                {"events": [{"event_key": f"k-{display_id}", "title": "t", "evidence_ids": [display_id]}]}
            )

    monkeypatch.setattr("app.skills.intelligence_extract.settings.mock_ai", False)
    persistence = FakePersistence()

    first = IntelligenceExtractSkill(llm_client=FakeClient()).run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "目标A"}, "evidence": _evidence()},
        persistence=persistence,
    )
    assert first.success is True
    assert calls == ["E-0001"]

    # 同一证据、同一持久化，但任务目标改变 → input_hash 失配 → 必须重新抽取，不复用旧目标缓存。
    calls.clear()
    second = IntelligenceExtractSkill(llm_client=FakeClient()).run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "目标B（不同）"}, "evidence": _evidence()},
        persistence=persistence,
    )
    assert second.success is True
    assert calls == ["E-0001"]


def test_real_extraction_all_batches_failed_returns_success_with_zero_done_stats(monkeypatch, tmp_path):
    class FakeClient:
        def generate_json(self, _system, _user, _schema):
            raise RuntimeError("boom")

    monkeypatch.setattr("app.skills.intelligence_extract.settings.mock_ai", False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_batch_max_items", 1, raising=False)
    persistence = FakePersistence()

    result = IntelligenceExtractSkill(llm_client=FakeClient()).run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "Analyze"}, "evidence": _evidence()},
        persistence=persistence,
    )

    assert result.success is True
    assert result.data["events"] == []
    assert result.metrics["batch_total"] == 2
    assert result.metrics["batch_done"] == 0
    assert result.metrics["batch_failed"] == 2
    assert [record[2] for record in persistence.records] == ["failed", "failed"]
    assert any("部分抽取失败：0/2 批成功、2 批失败" in warning for warning in result.warnings)
    assert "真实模型未抽取到任何要素，请检查模型/提示词" in result.warnings


def test_real_extraction_records_failed_batch_and_continues_unstarted_batches(monkeypatch, tmp_path):
    call_count = 0

    class FakeClient:
        def generate_json(self, _system, user, schema):
            nonlocal call_count
            call_count += 1
            display_id = re.search(r"\[(E-\d{4})\]", user).group(1)
            if display_id == "E-0001":
                raise RuntimeError("boom")
            time.sleep(0.02)
            return schema.model_validate(
                {
                    "events": [
                        {
                            "event_key": f"分队-发现-{display_id}",
                            "title": "发现车辆",
                            "evidence_ids": [display_id],
                        }
                    ]
                }
            )

    monkeypatch.setattr("app.skills.intelligence_extract.settings.mock_ai", False)
    monkeypatch.setattr("app.skills.intelligence_extract.settings.extract_concurrency", 2, raising=False)

    result = IntelligenceExtractSkill(llm_client=FakeClient()).run(
        _context(tmp_path),
        {"task": {"name": "Case", "objective": "Analyze"}, "evidence": _many_evidence(95)},
    )

    assert result.success is True
    assert result.metrics["batch_total"] == 4
    assert result.metrics["batch_done"] == 3
    assert result.metrics["batch_failed"] == 1
    assert call_count == 4


def test_merge_extractions_combines_evidence_ids_for_same_fact():
    first = ExtractionResult(
        events=[
            Event(
                event_key="车队-发现-车辆",
                title="发现车辆",
                time_normalized="2026-06-01T14:00:00",
                location="地点A",
                evidence_ids=["E-0001"],
                time_citation=FieldCitation(value="14:00", evidence_ids=["E-0001"], citation_origin="fallback"),
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
                time_citation=FieldCitation(
                    value="14:00",
                    evidence_ids=["E-0002", "E-0001"],
                    citation_origin="explicit",
                ),
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
        citation_origin="explicit",
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
