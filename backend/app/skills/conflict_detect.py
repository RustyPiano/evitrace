import itertools
import re
from datetime import date, datetime
from time import perf_counter
from typing import Any

from app.config import settings
from app.constants import CONFLICT_STATUS_UNREVIEWED
from app.schemas_analysis import Conflict
from app.utils.time_normalize import parse_time_value

from .base import SkillContext, SkillManifest, SkillResult

LOCATION_PUNCTUATION_RE = re.compile(r"[\s,，.。;；:：、\-_\[\]【】()（）]+")
UNKNOWN_VALUES = {"", "未知", "unknown", "null", "none"}


def _meaningful(value: str | None) -> str:
    text = str(value or "").strip()
    return "" if text.casefold() in UNKNOWN_VALUES else text


def _normalize_location(value: str | None) -> str:
    return LOCATION_PUNCTUATION_RE.sub("", _meaningful(value)).casefold()


def _event_side(event: dict[str, Any], value: str) -> dict[str, Any]:
    return {
        "value": value,
        "event_id": event["event_id"],
        "evidence_ids": event["evidence_ids"],
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
        left=_event_side(left_event, left_value),
        right=_event_side(right_event, right_value),
        status=CONFLICT_STATUS_UNREVIEWED,
    )
    conflicts.append(conflict.model_dump(mode="json"))


def _time_conflict(left: dict[str, Any], right: dict[str, Any], threshold_minutes: int) -> tuple[str, str] | None:
    left_time = parse_time_value(left.get("time_normalized"))
    right_time = parse_time_value(right.get("time_normalized"))
    if left_time is None or right_time is None:
        return None

    left_value = str(left.get("time_text") or left.get("time_normalized"))
    right_value = str(right.get("time_text") or right.get("time_normalized"))
    if left_time.kind == "date" or right_time.kind == "date":
        left_date = left_time.value if isinstance(left_time.value, date) else left_time.value.date()
        right_date = right_time.value if isinstance(right_time.value, date) else right_time.value.date()
        return (left_value, right_value) if left_date != right_date else None

    if not isinstance(left_time.value, datetime) or not isinstance(right_time.value, datetime):
        return None
    delta_minutes = abs((left_time.value - right_time.value).total_seconds()) / 60
    return (left_value, right_value) if delta_minutes > threshold_minutes else None


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
) -> tuple[list[dict[str, Any]], list[str]]:
    threshold = settings.time_conflict_minutes if time_conflict_minutes is None else time_conflict_minutes
    groups: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        event_key = str(event.get("event_key") or "").strip()
        if event_key:
            groups.setdefault(event_key, []).append(event)

    conflicts: list[dict[str, Any]] = []
    warnings: list[str] = []
    for event_key, group in groups.items():
        if len(group) < 2:
            continue
        for left, right in itertools.combinations(group, 2):
            time_values = _time_conflict(left, right, threshold)
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
            if left_location and right_location and _normalize_location(left_location) != _normalize_location(right_location):
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
        conflicts, warnings = detect_conflicts(list(payload.get("events") or []))
        return SkillResult(
            success=True,
            warnings=warnings,
            data={"conflicts": conflicts},
            metrics={"duration_ms": int((perf_counter() - started) * 1000), "conflict_count": len(conflicts)},
        )
