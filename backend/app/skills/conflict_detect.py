import itertools
import json
from datetime import date, datetime, time, timezone
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import Any

from app.config import settings
from app.constants import CONFLICT_STATUS_UNREVIEWED
from app.schemas_analysis import Conflict
from app.utils.event_normalize import (
    _norm,
    canonical_event_key,
    canonical_structured_key,
    group_events_for_conflict,
    normalize_location_alias,
)
from app.utils.time_normalize import parse_time_value

from .base import SkillContext, SkillManifest, SkillResult

UNKNOWN_VALUES = {"", "未知", "unknown", "null", "none"}


def _meaningful(value: str | None) -> str:
    text = str(value or "").strip()
    return "" if text.casefold() in UNKNOWN_VALUES else text


def _normalize_conflict_location(
    value: str | None, alias_map: dict[str, str] | None
) -> str:
    return normalize_location_alias(_meaningful(value), alias_map)


def _raw_event_key(event: dict[str, Any]) -> str:
    return str(event.get("event_key") or "").strip()


def _event_has_comparison_key(event: dict[str, Any]) -> bool:
    return bool(_norm(event.get("event_key")) or canonical_structured_key(event))


def _group_event_key(group: list[dict[str, Any]]) -> str:
    for event in group:
        event_key = _raw_event_key(event)
        if event_key:
            return event_key

    event_key = canonical_event_key(group[0]) if group else ""
    if event_key:
        return event_key

    for event in group:
        event_key = canonical_event_key(event)
        if event_key:
            return event_key
    return ""


def _field_evidence_ids(event: dict[str, Any], conflict_type: str) -> list[str]:
    citation_key = {
        "time": "time_citation",
        "location": "location_citation",
        "quantity": "quantity_citation",
    }.get(conflict_type)
    if citation_key:
        citation = event.get(citation_key)
        if isinstance(citation, dict):
            evidence_ids = [str(value) for value in citation.get("evidence_ids") or [] if value]
            if evidence_ids:
                return evidence_ids
    return [str(value) for value in event.get("evidence_ids") or [] if value]


def _event_side(event: dict[str, Any], value: str, conflict_type: str) -> dict[str, Any]:
    return {
        "value": value,
        "event_id": event["event_id"],
        "evidence_ids": _field_evidence_ids(event, conflict_type),
    }


def _add_conflict(
    conflicts: list[dict[str, Any]],
    *,
    conflict_type: str,
    event_key: str,
    description: str,
    left_event: dict[str, Any],
    left_value: str,
    right_event: dict[str, Any],
    right_value: str,
) -> None:
    conflict = Conflict(
        conflict_id=f"C-{len(conflicts) + 1:03d}",
        type=conflict_type,
        event_key=event_key,
        description=description,
        left=_event_side(left_event, left_value, conflict_type),
        right=_event_side(right_event, right_value, conflict_type),
        status=CONFLICT_STATUS_UNREVIEWED,
    )
    conflicts.append(conflict.model_dump(mode="json"))


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _as_utc_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _date_part(parsed_value: Any, kind: str) -> date | None:
    if kind == "date" and isinstance(parsed_value, date) and not isinstance(parsed_value, datetime):
        return parsed_value
    if kind == "datetime" and isinstance(parsed_value, datetime):
        return parsed_value.date()
    return None


def _time_minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _time_conflict(
    left: dict[str, Any],
    right: dict[str, Any],
    threshold_minutes: int,
) -> tuple[tuple[str, str] | None, str | None]:
    # Prefer the normalized time, but fall back to the raw time_text when the
    # model could not produce an ISO value (e.g. a bare clock time like "14:00"
    # with no date). parse_time_value handles both, so this keeps cross-source
    # conflict detection working on real-LLM output that leaves time_normalized null.
    left_time = parse_time_value(left.get("time_normalized")) or parse_time_value(
        left.get("time_text")
    )
    right_time = parse_time_value(right.get("time_normalized")) or parse_time_value(
        right.get("time_text")
    )
    if left_time is None or right_time is None:
        return None, None

    left_value = str(left.get("time_text") or left.get("time_normalized"))
    right_value = str(right.get("time_text") or right.get("time_normalized"))
    if left_time.kind == "date" or right_time.kind == "date":
        left_date = _date_part(left_time.value, left_time.kind)
        right_date = _date_part(right_time.value, right_time.kind)
        if left_date is None or right_date is None:
            return None, None
        return ((left_value, right_value), None) if left_date != right_date else (None, None)

    if left_time.kind == "time" or right_time.kind == "time":
        if isinstance(left_time.value, time) and isinstance(right_time.value, time):
            delta_minutes = abs(_time_minutes(left_time.value) - _time_minutes(right_time.value))
            return ((left_value, right_value), None) if delta_minutes > threshold_minutes else (None, None)
        warning = f"{left['event_id']}/{right['event_id']} 时间缺少日期上下文，未自动判定冲突"
        return None, warning

    if not isinstance(left_time.value, datetime) or not isinstance(right_time.value, datetime):
        return None, None
    left_aware = _is_aware(left_time.value)
    right_aware = _is_aware(right_time.value)
    if left_aware != right_aware:
        return None, f"{left['event_id']}/{right['event_id']} 时间时区信息不一致，未自动判定冲突"
    left_dt = _as_utc_naive(left_time.value) if left_aware else left_time.value
    right_dt = _as_utc_naive(right_time.value) if right_aware else right_time.value
    delta_minutes = abs((left_dt - right_dt).total_seconds()) / 60
    return ((left_value, right_value), None) if delta_minutes > threshold_minutes else (None, None)


def _quantity(event: dict[str, Any]) -> tuple[float, str] | None:
    quantity = event.get("quantity")
    if not isinstance(quantity, dict):
        return None
    unit = str(quantity.get("unit") or "").strip()
    if not unit:
        return None
    try:
        value = float(quantity.get("value"))
    except (TypeError, ValueError):
        return None
    return value, unit


def detect_conflicts(
    events: list[dict[str, Any]],
    *,
    time_conflict_minutes: int | None = None,
    alias_map: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    threshold = (
        settings.time_conflict_minutes
        if time_conflict_minutes is None
        else time_conflict_minutes
    )
    groups = group_events_for_conflict(events, alias_map)

    conflicts: list[dict[str, Any]] = []
    warnings: list[str] = []
    missing_key_event_ids = [
        str(event.get("event_id") or "unknown")
        for event in events
        if not _event_has_comparison_key(event)
    ]
    if missing_key_event_ids:
        sample = ", ".join(missing_key_event_ids[:5])
        if len(missing_key_event_ids) > 5:
            sample = f"{sample}, ..."
        warnings.append(
            f"{len(missing_key_event_ids)} 个事件缺少可归一化事件键，未参与冲突比对（示例: {sample}）"
        )

    for group in groups:
        if len(group) < 2:
            continue
        event_key = _group_event_key(group)
        if not event_key:
            continue
        for left, right in itertools.combinations(group, 2):
            time_values, time_warning = _time_conflict(left, right, threshold)
            if time_warning is not None:
                warnings.append(time_warning)
            if time_values is not None:
                _add_conflict(
                    conflicts,
                    conflict_type="time",
                    event_key=event_key,
                    description=f"同一事件存在 {time_values[0]} 与 {time_values[1]} 两种时间表述",
                    left_event=left,
                    left_value=time_values[0],
                    right_event=right,
                    right_value=time_values[1],
                )

            left_location = _meaningful(left.get("location"))
            right_location = _meaningful(right.get("location"))
            if (
                left_location
                and right_location
                and _normalize_conflict_location(left_location, alias_map)
                != _normalize_conflict_location(right_location, alias_map)
            ):
                _add_conflict(
                    conflicts,
                    conflict_type="location",
                    event_key=event_key,
                    description=f"同一事件存在 {left_location} 与 {right_location} 两种地点表述",
                    left_event=left,
                    left_value=left_location,
                    right_event=right,
                    right_value=right_location,
                )

            left_quantity = _quantity(left)
            right_quantity = _quantity(right)
            if left_quantity is None or right_quantity is None:
                continue
            left_value, left_unit = left_quantity
            right_value, right_unit = right_quantity
            if left_unit != right_unit:
                warnings.append(f"{left['event_id']}/{right['event_id']} 数量单位不同，未自动判定冲突")
                continue
            if left_value != right_value:
                left_text = f"{left_value:g} {left_unit}"
                right_text = f"{right_value:g} {right_unit}"
                _add_conflict(
                    conflicts,
                    conflict_type="quantity",
                    event_key=event_key,
                    description=f"同一事件存在 {left_text} 与 {right_text} 两种数量表述",
                    left_event=left,
                    left_value=left_text,
                    right_event=right,
                    right_value=right_text,
                )

    return conflicts, warnings


@lru_cache
def _load_event_alias_map(alias_path: str | None) -> tuple[dict[str, str], list[str]]:
    if not alias_path:
        return {}, []
    try:
        path = Path(alias_path).expanduser()
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, [f"EVENT_ALIAS_PATH 加载失败，已忽略别名配置: {type(exc).__name__}"]
    if not isinstance(data, dict):
        return {}, ["EVENT_ALIAS_PATH 内容必须是 JSON 对象，已忽略别名配置"]

    aliases: dict[str, str] = {}
    for surface, canonical in data.items():
        if (
            isinstance(surface, str)
            and isinstance(canonical, str)
            and surface.strip()
            and canonical.strip()
        ):
            aliases[surface] = canonical
    return aliases, []


class ConflictDetectSkill:
    manifest = SkillManifest(
        id="conflict_detect",
        name="冲突检测",
        version="1.0.0",
        description="检测时间、地点和数量冲突",
        enabled_by_default=True,
        required=True,
        input_types=["events"],
        output_type="conflict_list",
    )

    def run(self, context: SkillContext, payload: Any) -> SkillResult:
        started = perf_counter()
        alias_map, alias_warnings = _load_event_alias_map(settings.event_alias_path)
        conflicts, warnings = detect_conflicts(
            list(payload.get("events") or []), alias_map=alias_map
        )
        return SkillResult(
            success=True,
            warnings=alias_warnings + warnings,
            data={"conflicts": conflicts},
            metrics={
                "duration_ms": int((perf_counter() - started) * 1000),
                "conflict_count": len(conflicts),
            },
        )
