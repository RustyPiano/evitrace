from typing import Any

from fastapi import status
from pydantic import BaseModel, Field

from app.config import settings
from app.constants import (
    FILE_STATUS_FAILED,
    FILE_STATUS_PARSED,
    FILE_STATUS_PARSING,
    FILE_STATUS_WARNING,
    RUN_STATUS_FAILED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCEEDED,
    TASK_STATUS_FAILED,
    TASK_STATUS_READY,
)
from app.database import SessionLocal
from app.models import Task, TaskFile, TaskRun, utc_now
from app.schemas import AppError
from app.services import result_service
from app.services.storage_service import PARSER_SKILL_BY_MODALITY, task_directory
from app.services.task_service import serialize_file, task_not_found
from app.skills.base import SkillContext
from app.skills.registry import get_skill, is_enabled
from app.utils.health_details import redact_health_detail


class ParseSummary(BaseModel):
    task_id: str
    run_id: str | None = None
    total_files: int = 0
    parsed_files: int = 0
    warning_files: int = 0
    failed_files: int = 0
    evidence_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _evidence_items(result_data: dict | list | None) -> list[dict[str, Any]]:
    if isinstance(result_data, list):
        raw_items = result_data
    elif isinstance(result_data, dict) and isinstance(result_data.get("evidence"), list):
        raw_items = result_data["evidence"]
    else:
        raw_items = []

    items: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        content = str(raw.get("content") or "").strip()
        locator = raw.get("locator")
        if not content or not isinstance(locator, dict):
            continue
        items.append(
            {
                "content": content,
                "modality": raw["modality"],
                "evidence_type": raw["evidence_type"],
                "locator": locator,
                "confidence": raw.get("confidence"),
            }
        )
    return items


def _frame_items(result_data: dict | list | None) -> list[dict[str, Any]]:
    if not isinstance(result_data, dict) or not isinstance(result_data.get("frames"), list):
        return []
    frames: list[dict[str, Any]] = []
    for raw in result_data["frames"]:
        if not isinstance(raw, dict):
            continue
        frame_path = str(raw.get("frame_path") or "")
        if not frame_path:
            continue
        frames.append({"timestamp_ms": int(raw.get("timestamp_ms", 0)), "frame_path": frame_path})
    return frames


def _parser_skill_ids(modality: str) -> list[str]:
    if modality == "image":
        return ["image_ocr", "visual_understand"]
    if modality == "video":
        return ["video_parse", "visual_understand"]
    skill_id = PARSER_SKILL_BY_MODALITY.get(modality)
    return [skill_id] if skill_id is not None else []


def _failure_is_fatal(skill_id: str, modality: str) -> bool:
    if skill_id in {"document_parse", "audio_transcribe", "video_parse"}:
        return True
    if skill_id == "image_ocr" and modality == "image":
        return False
    return False


def _validate_frame_paths(task_id: str, items: list[dict[str, Any]]) -> None:
    root = task_directory(task_id)
    derived_root = (root / "derived").resolve()
    for item in items:
        locator = item["locator"]
        if locator.get("kind") != "video_frame":
            continue
        frame_path = str(locator.get("frame_path") or "")
        absolute = (root / frame_path).resolve()
        if not absolute.is_relative_to(derived_root):
            raise AppError("FORBIDDEN", "关键帧路径非法", status.HTTP_403_FORBIDDEN)


def _clamp_progress(value: int) -> int:
    return max(0, min(100, value))


def _scaled_progress(index: int, total: int, progress_start: int, progress_end: int) -> int:
    start = _clamp_progress(progress_start)
    end = max(start, _clamp_progress(progress_end))
    if total <= 0:
        return end
    bounded_index = max(0, min(total, index))
    return int(start + ((end - start) * bounded_index / total))


def _mark_run_progress(
    db,
    run_id: str | None,
    index: int,
    total: int,
    current_step: str | None,
    progress_start: int,
    progress_end: int,
) -> None:
    if run_id is None:
        return
    run = db.get(TaskRun, run_id)
    if run is None:
        return
    run.status = RUN_STATUS_RUNNING
    run.current_step = current_step
    run.progress = max(run.progress or 0, _scaled_progress(index, total, progress_start, progress_end))


def _safe_parse_detail(value: object) -> str:
    return redact_health_detail(value)


def _safe_join_details(values: list[str], fallback: str) -> str:
    safe_values = [_safe_parse_detail(value) for value in values if str(value or "").strip()]
    return "; ".join(safe_values) or fallback


def _cleanup_file_derived_artifacts(task_id: str, file_id: str, run_id: str | None) -> None:
    root = task_directory(task_id)
    relative_dirs = (
        (f"derived/runs/{run_id}/frames", f"derived/runs/{run_id}/audio")
        if run_id is not None
        else ("derived/frames", "derived/audio")
    )
    for relative_dir in relative_dirs:
        directory = root / relative_dir
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if not path.is_file():
                continue
            if path.name == f"{file_id}.wav" or path.name.startswith(f"{file_id}_"):
                path.unlink(missing_ok=True)


def _summary_message(summary: ParseSummary) -> str | None:
    combined = [_safe_parse_detail(item) for item in summary.errors + summary.warnings]
    return "; ".join(combined)[:1000] if combined else None


def parse_all_files(
    task_id: str,
    run_id: str | None = None,
    progress_start: int = 0,
    progress_end: int = 100,
) -> ParseSummary:
    summary = ParseSummary(task_id=task_id, run_id=run_id)
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if task is None:
            raise task_not_found()
        files = (
            db.query(TaskFile)
            .filter(TaskFile.task_id == task.id)
            .order_by(TaskFile.created_at.asc())
            .all()
        )
        if not files:
            raise AppError("TASK_NOT_READY", "无可分析文件", status.HTTP_409_CONFLICT)

        if run_id is not None:
            run = db.get(TaskRun, run_id)
            if run is not None:
                run.status = RUN_STATUS_RUNNING
                run.progress = max(run.progress or 0, _clamp_progress(progress_start))
                run.current_step = "parsing"
        db.commit()

        summary.total_files = len(files)
        mark_progress = lambda current_index, current_step: _mark_run_progress(
            db,
            run_id,
            current_index,
            len(files),
            current_step,
            progress_start,
            progress_end,
        )
        for index, file in enumerate(files, start=1):
            skill_ids = _parser_skill_ids(file.modality)
            result_service.delete_file_evidence(db, file.id, run_id=run_id)
            _cleanup_file_derived_artifacts(task.id, file.id, run_id)
            if not skill_ids:
                file.status = FILE_STATUS_WARNING
                file.error_message = f"unsupported modality: {file.modality}"
                summary.warning_files += 1
                summary.warnings.append(f"{file.original_name}: {file.error_message}")
                mark_progress(index, file.original_name)
                db.commit()
                continue

            file.status = FILE_STATUS_PARSING
            file.error_message = None
            mark_progress(index - 1, file.original_name)
            db.commit()

            context = SkillContext(task_id=task.id, run_id=run_id, data_root=str(settings.data_root_path))
            serialized_file = serialize_file(file)
            collected_items: list[dict[str, Any]] = []
            file_warnings: list[str] = []
            file_errors: list[str] = []
            video_frames: list[dict[str, Any]] = []

            for skill_id in skill_ids:
                if not is_enabled(db, skill_id):
                    file_warnings.append(f"{skill_id} disabled")
                    continue

                try:
                    skill = get_skill(skill_id)
                    payload: dict[str, Any] = {"file": serialized_file}
                    if skill_id == "visual_understand" and file.modality == "video":
                        payload["frames"] = video_frames
                    result = skill.run(context, payload)
                    if not result.success:
                        message = _safe_join_details(result.errors, "解析失败")
                        detail = f"{skill_id} failed: {message}"
                        if _failure_is_fatal(skill_id, file.modality):
                            file_errors.append(detail)
                            break
                        file_warnings.append(detail)
                        continue

                    if skill_id == "video_parse":
                        video_frames = _frame_items(result.data)

                    items = _evidence_items(result.data)
                    _validate_frame_paths(task.id, items)
                    for item in items:
                        item["file_id"] = file.id
                        item["skill_id"] = skill_id
                    collected_items.extend(items)

                    if result.warnings:
                        file_warnings.extend(_safe_parse_detail(warning) for warning in result.warnings)
                except Exception as exc:
                    message = _safe_parse_detail(getattr(exc, "message", str(exc)))
                    detail = f"{skill_id} failed: {message}"
                    if _failure_is_fatal(skill_id, file.modality):
                        file_errors.append(detail)
                        break
                    file_warnings.append(detail)

            if file_errors:
                message = _safe_join_details(file_errors, "解析失败")
                file.status = FILE_STATUS_FAILED
                file.error_message = message
                summary.failed_files += 1
                summary.errors.append(f"{file.original_name}: {message}")
            else:
                _validate_frame_paths(task.id, collected_items)
                created = result_service.create_evidence_batch(db, task.id, collected_items, run_id=run_id)
                summary.evidence_count += len(created)

                if file_warnings:
                    file.status = FILE_STATUS_WARNING
                    file.error_message = "; ".join(file_warnings)
                    summary.warning_files += 1
                    summary.warnings.extend(f"{file.original_name}: {warning}" for warning in file_warnings)
                else:
                    file.status = FILE_STATUS_PARSED
                    file.error_message = None
                    summary.parsed_files += 1

            mark_progress(index, file.original_name)
            db.commit()

        db.commit()

    return summary


def parse_task_files_for_endpoint(task_id: str, run_id: str) -> ParseSummary | None:
    try:
        summary = parse_all_files(task_id, run_id=run_id)
    except Exception as exc:
        error_message = _safe_parse_detail(exc)
        with SessionLocal() as db:
            task = db.get(Task, task_id)
            if task is not None:
                task.status = TASK_STATUS_FAILED
                task.last_error = error_message
            run = db.get(TaskRun, run_id)
            if run is not None:
                run.status = RUN_STATUS_FAILED
                run.current_step = "failed"
                run.error_message = error_message
                run.finished_at = utc_now()
            db.commit()
        raise

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if task is not None:
            task.status = TASK_STATUS_READY
            task.last_error = _summary_message(summary)
        run = db.get(TaskRun, run_id)
        if run is not None:
            run.status = RUN_STATUS_SUCCEEDED
            run.current_step = "parsed"
            run.progress = 100
            run.error_message = None
            run.finished_at = utc_now()
        db.commit()
    return summary
