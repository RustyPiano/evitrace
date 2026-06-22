import json
import re
from typing import Any

from fastapi import status
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.constants import ROLE_ADMIN
from app.models import Evidence, TaskFile, User
from app.schemas import AppError
from app.services.storage_service import task_directory
from app.services.task_service import ensure_task_access, serialize_file, task_not_found

DISPLAY_ID_RE = re.compile(r"^E-(\d+)$")
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 50


def serialize_locator(locator: dict[str, Any]) -> str:
    return json.dumps(locator, ensure_ascii=False)


def deserialize_locator(value: str) -> dict[str, Any]:
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def next_display_id(db: Session, task_id: str) -> str:
    display_ids = db.query(Evidence.display_id).filter(Evidence.task_id == task_id).all()
    max_number = 0
    for (display_id,) in display_ids:
        match = DISPLAY_ID_RE.match(display_id or "")
        if match:
            max_number = max(max_number, int(match.group(1)))
    return f"E-{max_number + 1:04d}"


def _next_display_number(db: Session, task_id: str) -> int:
    return int(next_display_id(db, task_id).removeprefix("E-"))


def create_evidence_batch(db: Session, task_id: str, items: list[dict[str, Any]]) -> list[Evidence]:
    if not items:
        return []

    next_number = _next_display_number(db, task_id)
    created: list[Evidence] = []
    for offset, item in enumerate(items):
        file = db.get(TaskFile, item["file_id"])
        if file is None or file.task_id != task_id:
            raise AppError("TASK_NOT_FOUND", "任务不存在或无权访问", status.HTTP_404_NOT_FOUND)

        evidence = Evidence(
            display_id=f"E-{next_number + offset:04d}",
            task_id=task_id,
            file_id=item["file_id"],
            modality=item["modality"],
            evidence_type=item["evidence_type"],
            content=item["content"],
            locator_json=serialize_locator(item.get("locator", {})),
            confidence=item.get("confidence"),
            skill_id=item["skill_id"],
        )
        db.add(evidence)
        created.append(evidence)

    db.flush()
    for evidence in created:
        evidence.display_id
        evidence.id
        db.expunge(evidence)
    return created


def delete_file_evidence(db: Session, file_id: str) -> int:
    return db.query(Evidence).filter(Evidence.file_id == file_id).delete()


def _serialize_evidence(evidence: Evidence, *, include_full_content: bool = False) -> dict[str, Any]:
    content = evidence.content if include_full_content else evidence.content[:240]
    file_data = serialize_file(evidence.file)
    return {
        "id": evidence.id,
        "display_id": evidence.display_id,
        "task_id": evidence.task_id,
        "file_id": evidence.file_id,
        "file": file_data,
        "modality": evidence.modality,
        "evidence_type": evidence.evidence_type,
        "content": content,
        "content_summary": evidence.content[:240],
        "locator": deserialize_locator(evidence.locator_json),
        "confidence": evidence.confidence,
        "skill_id": evidence.skill_id,
        "created_at": evidence.created_at.isoformat() if evidence.created_at else None,
    }


def list_task_evidence(
    db: Session,
    task_id: str,
    current_user: User,
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    file_id: str | None = None,
    modality: str | None = None,
) -> dict[str, Any]:
    task = ensure_task_access(db, task_id, current_user)
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    query = db.query(Evidence).filter(Evidence.task_id == task.id)
    if file_id:
        query = query.filter(Evidence.file_id == file_id)
    if modality:
        query = query.filter(Evidence.modality == modality)

    total = query.with_entities(func.count(Evidence.id)).scalar() or 0
    items = (
        query.order_by(Evidence.display_id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [_serialize_evidence(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def list_task_evidence_index(
    db: Session,
    task_id: str,
    current_user: User,
) -> list[dict[str, Any]]:
    task = ensure_task_access(db, task_id, current_user)
    items = (
        db.query(
            Evidence.id,
            Evidence.display_id,
            Evidence.modality,
            Evidence.evidence_type,
        )
        .filter(Evidence.task_id == task.id)
        .order_by(Evidence.display_id.asc())
        .all()
    )
    return [
        {
            "id": item.id,
            "display_id": item.display_id,
            "modality": item.modality,
            "evidence_type": item.evidence_type,
        }
        for item in items
    ]


def get_evidence_with_access(db: Session, evidence_id: str, current_user: User) -> Evidence:
    evidence = db.get(Evidence, evidence_id)
    if evidence is None:
        raise task_not_found()
    if current_user.role != ROLE_ADMIN:
        ensure_task_access(db, evidence.task_id, current_user)
    return evidence


def get_evidence_detail(db: Session, evidence_id: str, current_user: User) -> dict[str, Any]:
    evidence = get_evidence_with_access(db, evidence_id, current_user)
    return _serialize_evidence(evidence, include_full_content=True)


def evidence_source(db: Session, evidence_id: str, current_user: User) -> dict[str, Any]:
    evidence = get_evidence_with_access(db, evidence_id, current_user)
    locator = deserialize_locator(evidence.locator_json)
    data = {
        "evidence_id": evidence.id,
        "display_id": evidence.display_id,
        "locator": locator,
        "file": serialize_file(evidence.file),
        "file_url": f"/api/v1/files/{evidence.file_id}/stream",
        "frame_url": None,
    }
    if locator.get("kind") == "video_frame":
        data["frame_url"] = f"/api/v1/evidence/{evidence.id}/frame"
    return data


def _safe_frame_path(evidence: Evidence) -> tuple[str, str]:
    locator = deserialize_locator(evidence.locator_json)
    if locator.get("kind") != "video_frame":
        raise AppError("FILE_TYPE_NOT_SUPPORTED", "该证据没有关键帧图片", status.HTTP_400_BAD_REQUEST)
    frame_path = str(locator.get("frame_path") or "")
    task_root = task_directory(evidence.task_id)
    frames_root = (task_root / "derived" / "frames").resolve()
    absolute = (task_root / frame_path).resolve()
    if not absolute.is_relative_to(frames_root):
        raise AppError("FORBIDDEN", "关键帧路径非法", status.HTTP_403_FORBIDDEN)
    if not absolute.is_file():
        raise AppError("TASK_NOT_FOUND", "关键帧不存在", status.HTTP_404_NOT_FOUND)
    return str(absolute), frame_path


def frame_file_response(db: Session, evidence_id: str, current_user: User) -> FileResponse:
    evidence = get_evidence_with_access(db, evidence_id, current_user)
    path, frame_path = _safe_frame_path(evidence)
    media_type = "image/jpeg" if frame_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
    return FileResponse(path, media_type=media_type, filename=frame_path.rsplit("/", 1)[-1])
