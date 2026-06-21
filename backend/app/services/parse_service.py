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
    TASK_STATUS_PARSING,
    TASK_STATUS_READY,
)
from app.database import SessionLocal
from app.models import Task, TaskFile, TaskRun
from app.schemas import AppError
from app.services import result_service
from app.services.storage_service import PARSER_SKILL_BY_MODALITY, task_directory
from app.services.task_service import serialize_file, task_not_found
from app.skills.base import SkillContext
from app.skills.registry import get_skill, is_enabled


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


def _validate_frame_paths(task_id: str, items: list[dict[str, Any]]) -> None:
    root = task_directory(task_id)
    frames_root = (root / "derived" / "frames").resolve()
    for item in items:
        locator = item["locator"]
        if locator.get("kind") != "video_frame":
            continue
        frame_path = str(locator.get("frame_path") or "")
        absolute = (root / frame_path).resolve()
        if not absolute.is_relative_to(frames_root):
            raise AppError("FORBIDDEN", "关键帧路径非法", status.HTTP_403_FORBIDDEN)


def _mark_run_progress(db, run_id: str | None, index: int, total: int, current_step: str | None) -> None:
    if run_id is None:
        return
    run = db.get(TaskRun, run_id)
    if run is None:
        return
    run.status = RUN_STATUS_RUNNING
    run.current_step = current_step
    run.progress = int(index / total * 100) if total else 0


def parse_all_files(task_id: str, run_id: str | None = None) -> ParseSummary:
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

        task.status = TASK_STATUS_PARSING
        task.last_error = None
        if run_id is not None:
            run = db.get(TaskRun, run_id)
            if run is not None:
                run.status = RUN_STATUS_RUNNING
                run.progress = 0
                run.current_step = "parsing"
        db.commit()

        summary.total_files = len(files)
        for index, file in enumerate(files, start=1):
            skill_id = PARSER_SKILL_BY_MODALITY.get(file.modality)
            result_service.delete_file_evidence(db, file.id)
            if skill_id is None:
                file.status = FILE_STATUS_WARNING
                file.error_message = f"unsupported modality: {file.modality}"
                summary.warning_files += 1
                summary.warnings.append(f"{file.original_name}: {file.error_message}")
                _mark_run_progress(db, run_id, index, len(files), file.original_name)
                db.commit()
                continue

            if not is_enabled(db, skill_id):
                file.status = FILE_STATUS_WARNING
                file.error_message = f"{skill_id} disabled"
                summary.warning_files += 1
                summary.warnings.append(f"{file.original_name}: {file.error_message}")
                _mark_run_progress(db, run_id, index, len(files), file.original_name)
                db.commit()
                continue

            file.status = FILE_STATUS_PARSING
            file.error_message = None
            _mark_run_progress(db, run_id, index - 1, len(files), file.original_name)
            db.commit()

            try:
                skill = get_skill(skill_id)
                context = SkillContext(task_id=task.id, run_id=run_id, data_root=str(settings.data_root_path))
                result = skill.run(context, {"file": serialize_file(file)})
                if not result.success:
                    message = "; ".join(result.errors) or "解析失败"
                    file.status = FILE_STATUS_FAILED
                    file.error_message = message
                    summary.failed_files += 1
                    summary.errors.append(f"{file.original_name}: {message}")
                    _mark_run_progress(db, run_id, index, len(files), file.original_name)
                    db.commit()
                    continue

                items = _evidence_items(result.data)
                _validate_frame_paths(task.id, items)
                for item in items:
                    item["file_id"] = file.id
                    item["skill_id"] = skill_id
                created = result_service.create_evidence_batch(db, task.id, items)
                summary.evidence_count += len(created)

                if result.warnings:
                    file.status = FILE_STATUS_WARNING
                    file.error_message = "; ".join(result.warnings)
                    summary.warning_files += 1
                    summary.warnings.extend(f"{file.original_name}: {warning}" for warning in result.warnings)
                else:
                    file.status = FILE_STATUS_PARSED
                    file.error_message = None
                    summary.parsed_files += 1
            except Exception as exc:
                message = getattr(exc, "message", str(exc))
                file.status = FILE_STATUS_FAILED
                file.error_message = message
                summary.failed_files += 1
                summary.errors.append(f"{file.original_name}: {message}")

            _mark_run_progress(db, run_id, index, len(files), file.original_name)
            db.commit()

        task = db.get(Task, task_id)
        if task is not None:
            task.status = TASK_STATUS_READY
            combined = summary.errors + summary.warnings
            task.last_error = "; ".join(combined)[:1000] if combined else None
        if run_id is not None:
            run = db.get(TaskRun, run_id)
            if run is not None:
                run.status = RUN_STATUS_FAILED if summary.errors else RUN_STATUS_SUCCEEDED
                run.progress = 100
                run.current_step = "parsing"
                run.error_message = "; ".join(summary.errors)[:1000] if summary.errors else None
        db.commit()

    return summary
