import json
import unicodedata
from pathlib import Path
from time import perf_counter
from typing import Any
from datetime import date, datetime, time, timezone

from app.config import settings
from app.schemas_analysis import Entity, Event, ExtractionResult, TimelineItem
from app.services.llm_client import LocalLLMClient
from app.utils.time_normalize import ParsedTime, parse_time_value

from .base import SkillContext, SkillManifest, SkillResult

BATCH_MAX_ITEMS = 30
BATCH_MAX_CHARS = 12_000


def _normalize_key(value: str | None) -> str:
    return unicodedata.normalize("NFKC", (value or "").strip()).casefold()


def _evidence_text(evidence: dict[str, Any]) -> str:
    return str(evidence.get("content") or evidence.get("content_summary") or "").strip()


def _source_name(evidence: dict[str, Any]) -> str:
    file_info = evidence.get("file") if isinstance(evidence.get("file"), dict) else {}
    return str(file_info.get("original_name") or "未知来源")


def _locator_text(evidence: dict[str, Any]) -> str:
    locator = evidence.get("locator")
    if not isinstance(locator, dict):
        return "-"
    if locator.get("kind") == "text":
        page = f"P{locator['page']}" if isinstance(locator.get("page"), int) else "文本"
        paragraph = f"段{locator['paragraph']}" if isinstance(locator.get("paragraph"), int) else ""
        return " ".join(part for part in (page, paragraph) if part)
    if isinstance(locator.get("start_ms"), int):
        return f"{locator['start_ms'] / 1000:.1f}s"
    if isinstance(locator.get("timestamp_ms"), int):
        return f"{locator['timestamp_ms'] / 1000:.1f}s"
    return str(locator.get("kind") or "-")


def _format_evidence_for_prompt(evidence: dict[str, Any]) -> str:
    display_id = evidence["display_id"]
    return f"[{display_id}][{_source_name(evidence)}][{_locator_text(evidence)}] {_evidence_text(evidence)[:1200]}"


def _batch_evidence(evidence_items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    for evidence in evidence_items:
        size = len(_format_evidence_for_prompt(evidence))
        if current and (len(current) >= BATCH_MAX_ITEMS or current_chars + size > BATCH_MAX_CHARS):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(evidence)
        current_chars += size
    if current:
        batches.append(current)
    return batches


def _fixture_path(context: SkillContext) -> Path:
    return Path(context.data_root) / "tasks" / context.task_id / "mock" / "extraction.json"


def _load_fixture(context: SkillContext) -> dict[str, Any] | None:
    path = _fixture_path(context)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_match(raw: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]) -> list[str] | None:
    match_text = str(raw.get("match") or "").strip()
    if not match_text:
        return None
    for display_id, evidence in evidence_by_id.items():
        if match_text in _evidence_text(evidence):
            return [display_id]
    return None


def _valid_evidence_ids(raw: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]) -> list[str]:
    matched = _resolve_match(raw, evidence_by_id)
    if matched:
        return matched
    raw_ids = raw.get("evidence_ids")
    if not isinstance(raw_ids, list):
        return []
    seen: set[str] = set()
    valid: list[str] = []
    for value in raw_ids:
        display_id = str(value)
        if display_id in evidence_by_id and display_id not in seen:
            valid.append(display_id)
            seen.add(display_id)
    return valid


def _default_mock_raw(evidence_items: list[dict[str, Any]]) -> dict[str, Any]:
    first = evidence_items[0]["display_id"]
    second = evidence_items[1]["display_id"] if len(evidence_items) > 1 else first
    return {
        "entities": [
            {"type": "organization", "name": "车队", "confidence": 0.8, "evidence_ids": [first]},
            {"type": "location", "name": "地点A", "confidence": 0.8, "evidence_ids": [first]},
            {"type": "location", "name": "地点B", "confidence": 0.8, "evidence_ids": [second]},
            {"type": "quantity", "name": "3 辆", "confidence": 0.8, "evidence_ids": [first]},
            {"type": "quantity", "name": "5 辆", "confidence": 0.8, "evidence_ids": [second]},
        ],
        "events": [
            {
                "event_key": "车队-发现-车辆",
                "title": "车队发现车辆",
                "subject": "车队",
                "action": "发现",
                "object": "车辆",
                "time_text": "2026-06-01 14:00",
                "time_normalized": "2026-06-01T14:00:00",
                "location": "地点A",
                "quantity": {"value": 3, "unit": "辆"},
                "evidence_ids": [first],
                "confidence": 0.82,
            },
            {
                "event_key": "车队-发现-车辆",
                "title": "车队发现车辆",
                "subject": "车队",
                "action": "发现",
                "object": "车辆",
                "time_text": "2026-06-01 16:30",
                "time_normalized": "2026-06-01T16:30:00",
                "location": "地点B",
                "quantity": {"value": 5, "unit": "辆"},
                "evidence_ids": [second],
                "confidence": 0.82,
            },
        ],
    }


def _sanitize_extraction(raw: dict[str, Any], evidence_items: list[dict[str, Any]]) -> tuple[ExtractionResult, list[str]]:
    evidence_by_id = {item["display_id"]: item for item in evidence_items}
    warnings: list[str] = []
    raw_entities = raw.get("entities") if isinstance(raw.get("entities"), list) else []
    raw_events = raw.get("events") if isinstance(raw.get("events"), list) else []

    entities: list[Entity] = []
    for raw_entity in raw_entities:
        if not isinstance(raw_entity, dict):
            continue
        normalized = dict(raw_entity)
        normalized["evidence_ids"] = _valid_evidence_ids(raw_entity, evidence_by_id)
        try:
            entities.append(Entity.model_validate(normalized))
        except Exception as exc:
            warnings.append(f"实体结果已丢弃: {type(exc).__name__}")

    events: list[Event] = []
    for raw_event in raw_events:
        if not isinstance(raw_event, dict):
            continue
        normalized = dict(raw_event)
        normalized["evidence_ids"] = _valid_evidence_ids(raw_event, evidence_by_id)
        if not normalized["evidence_ids"]:
            warnings.append("事件结果因缺少有效证据引用已丢弃")
            continue
        if normalized.get("time_normalized") and parse_time_value(str(normalized["time_normalized"])) is None:
            normalized["time_normalized"] = None
            warnings.append("事件时间规范化值不可解析，已置为未确定")
        normalized.pop("event_id", None)
        try:
            events.append(Event.model_validate(normalized))
        except Exception as exc:
            warnings.append(f"事件结果已丢弃: {type(exc).__name__}")

    return ExtractionResult(entities=entities, events=events), warnings


def _merge_extractions(extractions: list[ExtractionResult]) -> ExtractionResult:
    entity_keys: set[tuple[str, str]] = set()
    entities: list[Entity] = []
    event_by_key: dict[tuple[str, tuple[str, str, str]], Event] = {}
    events: list[Event] = []

    for extraction in extractions:
        for entity in extraction.entities:
            key = (entity.type, _normalize_key(entity.name))
            if key in entity_keys:
                continue
            entity_keys.add(key)
            entities.append(entity)

        for event in extraction.events:
            fact_key = (
                _normalize_key(event.time_normalized or event.time_text),
                _normalize_key(event.location),
                event.quantity.model_dump_json() if event.quantity else "",
            )
            key = (_normalize_key(event.event_key), fact_key)
            existing = event_by_key.get(key)
            if existing is not None:
                for evidence_id in event.evidence_ids:
                    if evidence_id not in existing.evidence_ids:
                        existing.evidence_ids.append(evidence_id)
                continue
            event.event_id = f"EVT-{len(events) + 1:03d}"
            event_by_key[key] = event
            events.append(event)

    return ExtractionResult(entities=entities, events=events)


def _timeline_sort_key(parsed: ParsedTime) -> datetime:
    value = parsed.value
    if isinstance(value, datetime):
        if value.tzinfo is not None and value.utcoffset() is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    return datetime.combine(date.min, value)


def build_timeline(events: list[Event]) -> list[TimelineItem]:
    dated: list[tuple[Event, ParsedTime]] = []
    undated: list[Event] = []
    for event in events:
        parsed = parse_time_value(event.time_normalized)
        if parsed is None:
            undated.append(event)
        else:
            dated.append((event, parsed))
    dated.sort(key=lambda item: _timeline_sort_key(item[1]))
    timeline: list[TimelineItem] = []
    for event in [item[0] for item in dated] + undated:
        timeline.append(
            TimelineItem(
                event_id=event.event_id or "",
                event_key=event.event_key,
                title=event.title,
                time_text=event.time_text,
                time_normalized=event.time_normalized,
                time_group=event.time_normalized or "时间未确定",
                location=event.location,
                evidence_ids=event.evidence_ids,
            )
        )
    return timeline


class IntelligenceExtractSkill:
    manifest = SkillManifest(
        id="intelligence_extract",
        name="要素事件提取",
        version="1.0.0",
        description="从证据列表提取实体、事件和时间线",
        enabled_by_default=True,
        required=True,
        input_types=["evidence_list"],
        output_type="analysis_entities_events",
    )

    def __init__(self, llm_client: LocalLLMClient | None = None) -> None:
        self.llm_client = llm_client

    def run(self, context: SkillContext, payload: Any) -> SkillResult:
        started = perf_counter()
        evidence_items = list(payload.get("evidence") or [])
        if not evidence_items:
            return SkillResult(success=False, errors=["没有可用于要素提取的证据"], data=None)

        warnings: list[str] = []
        try:
            if settings.mock_ai:
                raw = _load_fixture(context) or _default_mock_raw(evidence_items)
                extraction, sanitize_warnings = _sanitize_extraction(raw, evidence_items)
                warnings.extend(sanitize_warnings)
            else:
                extraction, real_warnings = self._run_real_extraction(payload, evidence_items)
                warnings.extend(real_warnings)
        except Exception as exc:
            return SkillResult(
                success=False,
                errors=[f"要素提取失败: {type(exc).__name__}: {exc}"],
                data=None,
                metrics={"duration_ms": int((perf_counter() - started) * 1000)},
            )

        extraction = _merge_extractions([extraction])
        timeline = build_timeline(extraction.events)
        return SkillResult(
            success=True,
            warnings=warnings,
            data={
                "entities": [entity.model_dump(mode="json") for entity in extraction.entities],
                "events": [event.model_dump(mode="json") for event in extraction.events],
                "timeline": [item.model_dump(mode="json") for item in timeline],
            },
            metrics={
                "duration_ms": int((perf_counter() - started) * 1000),
                "entity_count": len(extraction.entities),
                "event_count": len(extraction.events),
            },
        )

    def _run_real_extraction(self, payload: Any, evidence_items: list[dict[str, Any]]) -> tuple[ExtractionResult, list[str]]:
        client = self.llm_client or LocalLLMClient()
        task = payload.get("task") or {}
        system_prompt = (
            "你是情报资料要素提取器。只使用输入证据；无法确定就输出 null；每个事件必须引用证据编号；"
            "不输出行动建议；不合并明显冲突事实；严格输出符合 schema 的 JSON。"
        )
        extractions: list[ExtractionResult] = []
        warnings: list[str] = []
        for batch in _batch_evidence(evidence_items):
            user_prompt = "\n".join(
                [
                    f"任务目标：{task.get('objective') or ''}",
                    "证据：",
                    *[_format_evidence_for_prompt(evidence) for evidence in batch],
                ]
            )
            result = client.generate_json(system_prompt, user_prompt, ExtractionResult)
            raw = result.model_dump(mode="json")
            sanitized, sanitize_warnings = _sanitize_extraction(raw, batch)
            warnings.extend(sanitize_warnings)
            extractions.append(sanitized)
        return _merge_extractions(extractions), warnings
