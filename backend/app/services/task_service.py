import json
import shutil
from datetime import datetime
from typing import Any

from fastapi import status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import (
    ROLE_ADMIN,
    TASK_RUNNING_STATUSES,
    TASK_STATUS_AWAITING_REVIEW,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_DRAFT,
)
from app.models import AnalysisResult, Evidence, Task, TaskFile, TaskRun, User
from app.schemas import AppError, TaskCreate, TaskUpdate
from app.services.audit_service import record_audit


def isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def task_not_found() -> AppError:
    return AppError(
        "TASK_NOT_FOUND",
        "任务不存在或无权访问",
        status.HTTP_404_NOT_FOUND,
    )


def ensure_task_access(db: Session, task_id: str, current_user: User) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise task_not_found()
    if current_user.role != ROLE_ADMIN and task.owner_id != current_user.id:
        raise task_not_found()
    return task


def serialize_file(file: TaskFile) -> dict[str, Any]:
    return {
        "id": file.id,
        "task_id": file.task_id,
        "original_name": file.original_name,
        "stored_name": file.stored_name,
        "extension": file.extension,
        "mime_type": file.mime_type,
        "size_bytes": file.size_bytes,
        "modality": file.modality,
        "status": file.status,
        "error_message": file.error_message,
        "created_at": isoformat(file.created_at),
    }


def serialize_task_summary(db: Session, task: Task) -> dict[str, Any]:
    file_count = db.query(func.count(TaskFile.id)).filter(TaskFile.task_id == task.id).scalar()
    latest_run = (
        db.query(TaskRun)
        .filter(TaskRun.task_id == task.id)
        .order_by(TaskRun.started_at.desc().nullslast(), TaskRun.finished_at.desc().nullslast())
        .first()
    )
    owner = db.get(User, task.owner_id)
    return {
        "id": task.id,
        "name": task.name,
        "objective": task.objective,
        "description": task.description,
        "owner_id": task.owner_id,
        "owner_username": owner.username if owner else None,
        "file_count": file_count or 0,
        "status": task.status,
        "last_error": task.last_error,
        "latest_run_error": latest_run.error_message if latest_run else None,
        "created_at": isoformat(task.created_at),
        "updated_at": isoformat(task.updated_at),
    }


def serialize_task_detail(db: Session, task: Task) -> dict[str, Any]:
    summary = serialize_task_summary(db, task)
    files = (
        db.query(TaskFile)
        .filter(TaskFile.task_id == task.id)
        .order_by(TaskFile.created_at.asc())
        .all()
    )
    evidence_count = db.query(func.count(Evidence.id)).filter(Evidence.task_id == task.id).scalar()
    summary.update(
        {
            "files": [serialize_file(file) for file in files],
            "evidence_count": evidence_count or 0,
            "entities": [],
            "timeline": [],
            "conflicts": [],
            "report_markdown": None,
        }
    )
    return summary


def _json_load(value: str, default: Any) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _validate_completion_gate(db: Session, task: Task, current_user: User, force: bool) -> None:
    result = db.query(AnalysisResult).filter(AnalysisResult.task_id == task.id).first()
    if result is None:
        raise AppError("CITATION_CHECK_REQUIRED", "缺少引用校验结果，无法完成任务", status.HTTP_409_CONFLICT)
    citation_check = _json_load(result.citation_check_json, {})
    if not isinstance(citation_check, dict):
        raise AppError("CITATION_CHECK_REQUIRED", "引用校验结果无效，无法完成任务", status.HTTP_409_CONFLICT)

    invalid_citations = citation_check.get("invalid_citations")
    if isinstance(invalid_citations, list) and invalid_citations:
        raise AppError("INVALID_CITATIONS_PRESENT", "报告存在无效证据引用，无法完成任务", status.HTTP_409_CONFLICT)

    try:
        coverage = float(citation_check.get("citation_coverage", 0))
    except (TypeError, ValueError):
        coverage = 0
    if coverage < 0.9 and not (current_user.role == ROLE_ADMIN and force):
        raise AppError(
            "CITATION_COVERAGE_TOO_LOW",
            "综合分析结论引用覆盖率低于 0.90，需管理员强制完成",
            status.HTTP_409_CONFLICT,
        )


def list_tasks(db: Session, current_user: User) -> list[dict[str, Any]]:
    query = db.query(Task).order_by(Task.updated_at.desc())
    if current_user.role != ROLE_ADMIN:
        query = query.filter(Task.owner_id == current_user.id)
    return [serialize_task_summary(db, task) for task in query.all()]


def create_task(db: Session, payload: TaskCreate, current_user: User) -> dict[str, Any]:
    task = Task(
        name=payload.name,
        objective=payload.objective,
        description=payload.description,
        owner_id=current_user.id,
        status=TASK_STATUS_DRAFT,
    )
    db.add(task)
    db.flush()
    record_audit(
        db,
        user_id=current_user.id,
        action="task_created",
        resource_type="task",
        resource_id=task.id,
        detail={"name": task.name},
    )
    db.commit()
    db.refresh(task)
    return serialize_task_detail(db, task)


def get_task_detail(db: Session, task_id: str, current_user: User) -> dict[str, Any]:
    task = ensure_task_access(db, task_id, current_user)
    return serialize_task_detail(db, task)


def update_task(
    db: Session,
    task_id: str,
    payload: TaskUpdate,
    current_user: User,
) -> dict[str, Any]:
    task = ensure_task_access(db, task_id, current_user)
    if payload.status is not None and payload.status != TASK_STATUS_COMPLETED:
        raise AppError("VALIDATION_ERROR", "仅支持标记为 completed", status.HTTP_422_UNPROCESSABLE_CONTENT)

    for field in ("name", "objective", "description"):
        value = getattr(payload, field)
        if value is not None:
            setattr(task, field, value)
    if payload.status == TASK_STATUS_COMPLETED:
        if task.status != TASK_STATUS_AWAITING_REVIEW:
            raise AppError(
                "INVALID_STATUS_TRANSITION",
                "仅允许 awaiting_review 任务标记为 completed",
                status.HTTP_409_CONFLICT,
            )
        _validate_completion_gate(db, task, current_user, payload.force)
        task.status = TASK_STATUS_COMPLETED

    db.commit()
    db.refresh(task)
    return serialize_task_detail(db, task)


def delete_task(db: Session, task_id: str, current_user: User) -> None:
    task = ensure_task_access(db, task_id, current_user)
    if task.status in TASK_RUNNING_STATUSES:
        raise AppError("TASK_ALREADY_RUNNING", "运行中任务不可删除", status.HTTP_409_CONFLICT)

    task_dir = settings.data_root_path / "tasks" / task.id
    if task_dir.exists():
        shutil.rmtree(task_dir)

    db.query(AnalysisResult).filter(AnalysisResult.task_id == task.id).delete()
    db.query(Evidence).filter(Evidence.task_id == task.id).delete()
    db.query(TaskRun).filter(TaskRun.task_id == task.id).delete()
    db.query(TaskFile).filter(TaskFile.task_id == task.id).delete()
    db.delete(task)
    record_audit(
        db,
        user_id=current_user.id,
        action="task_deleted",
        resource_type="task",
        resource_id=task_id,
        detail={"name": task.name},
    )
    db.commit()
