from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import (
    FILE_STATUS_UPLOADED,
    FILE_STATUS_WARNING,
    TASK_RUNNING_STATUSES,
    TASK_STATUS_DRAFT,
    TASK_STATUS_READY,
)
from app.models import Evidence, SkillConfig, Task, TaskFile, User
from app.schemas import AppError
from app.services.audit_service import record_audit
from app.services.task_service import ensure_task_access, serialize_file, task_not_found
from app.utils.file_types import HEADER_READ_BYTES, validate_file_signature, validate_upload_type

CHUNK_SIZE = 1024 * 1024
PARSER_SKILL_BY_MODALITY = {
    "text": "document_parse",
    "document": "document_parse",
    "image": "image_ocr",
    "audio": "audio_transcribe",
    "video": "video_parse",
}


def task_directory(task_id: str) -> Path:
    return (settings.data_root_path / "tasks" / task_id).resolve()


def original_directory(task_id: str) -> Path:
    return task_directory(task_id) / "original"


def ensure_original_directory(task_id: str) -> Path:
    directory = original_directory(task_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def safe_original_path(task_id: str, stored_name: str) -> Path:
    root = task_directory(task_id)
    path = (root / "original" / stored_name).resolve()
    if not path.is_relative_to(root):
        raise AppError("FORBIDDEN", "文件路径非法", status.HTTP_403_FORBIDDEN)
    return path


def max_upload_bytes() -> int:
    return settings.max_upload_mb * 1024 * 1024


def initial_file_status(db: Session, modality: str) -> tuple[str, str | None]:
    skill_id = PARSER_SKILL_BY_MODALITY[modality]
    config = db.get(SkillConfig, skill_id)
    if config is not None and not config.enabled:
        return FILE_STATUS_WARNING, f"{skill_id} disabled"
    return FILE_STATUS_UPLOADED, None


async def upload_task_files(
    db: Session,
    task_id: str,
    files: list[UploadFile],
    current_user: User,
) -> list[dict]:
    task = ensure_task_access(db, task_id, current_user)
    saved_paths: list[Path] = []
    created_files: list[TaskFile] = []
    directory = ensure_original_directory(task.id)

    try:
        for upload in files:
            original_name, extension, modality = validate_upload_type(
                upload.filename,
                upload.content_type,
            )
            file_id = uuid4().hex
            stored_name = f"{file_id}.{extension}"
            destination = (directory / stored_name).resolve()
            if not destination.is_relative_to(task_directory(task.id)):
                raise AppError("FORBIDDEN", "文件路径非法", status.HTTP_403_FORBIDDEN)

            size = 0
            saved_paths.append(destination)
            try:
                with destination.open("wb") as output:
                    header = await upload.read(HEADER_READ_BYTES)
                    validate_file_signature(extension, header)
                    size += len(header)
                    if size > max_upload_bytes():
                        raise AppError("FILE_TOO_LARGE", "文件过大", status.HTTP_413_CONTENT_TOO_LARGE)
                    output.write(header)
                    while True:
                        chunk = await upload.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > max_upload_bytes():
                            raise AppError("FILE_TOO_LARGE", "文件过大", status.HTTP_413_CONTENT_TOO_LARGE)
                        output.write(chunk)
            finally:
                await upload.close()

            file_status, error_message = initial_file_status(db, modality)
            task_file = TaskFile(
                id=file_id,
                task_id=task.id,
                original_name=original_name,
                stored_name=stored_name,
                extension=extension,
                mime_type=upload.content_type,
                size_bytes=size,
                modality=modality,
                status=file_status,
                error_message=error_message,
            )
            db.add(task_file)
            created_files.append(task_file)

        if created_files and task.status == TASK_STATUS_DRAFT:
            task.status = TASK_STATUS_READY

        record_audit(
            db,
            user_id=current_user.id,
            action="file_uploaded",
            resource_type="task",
            resource_id=task.id,
            detail={"file_count": len(created_files)},
        )
        db.commit()
    except Exception:
        db.rollback()
        for path in saved_paths:
            path.unlink(missing_ok=True)
        raise

    for task_file in created_files:
        db.refresh(task_file)
    return [serialize_file(task_file) for task_file in created_files]


def list_task_files(db: Session, task_id: str, current_user: User) -> list[dict]:
    task = ensure_task_access(db, task_id, current_user)
    files = (
        db.query(TaskFile)
        .filter(TaskFile.task_id == task.id)
        .order_by(TaskFile.created_at.asc())
        .all()
    )
    return [serialize_file(file) for file in files]


def get_file_with_task_access(db: Session, file_id: str, current_user: User) -> TaskFile:
    file = db.get(TaskFile, file_id)
    if file is None:
        raise task_not_found()
    ensure_task_access(db, file.task_id, current_user)
    return file


def delete_file(db: Session, file_id: str, current_user: User) -> None:
    file = get_file_with_task_access(db, file_id, current_user)
    task = db.get(Task, file.task_id)
    if task is None:
        raise task_not_found()
    if task.status in TASK_RUNNING_STATUSES:
        raise AppError("TASK_ALREADY_RUNNING", "运行中任务不可删除文件", status.HTTP_409_CONFLICT)
    if task.status not in {TASK_STATUS_DRAFT, TASK_STATUS_READY}:
        raise AppError(
            "FILE_DELETE_NOT_ALLOWED",
            "已分析任务不可直接删除文件，请重新分析任务",
            status.HTTP_409_CONFLICT,
        )

    safe_original_path(file.task_id, file.stored_name).unlink(missing_ok=True)
    db.query(Evidence).filter(Evidence.file_id == file.id).delete()
    db.delete(file)
    remaining = (
        db.query(func.count(TaskFile.id))
        .filter(TaskFile.task_id == task.id, TaskFile.id != file.id)
        .scalar()
    )
    if not remaining:
        task.status = TASK_STATUS_DRAFT

    record_audit(
        db,
        user_id=current_user.id,
        action="file_deleted",
        resource_type="file",
        resource_id=file.id,
        detail={"task_id": task.id, "original_name": file.original_name},
    )
    db.commit()


def parse_range_header(range_header: str | None, file_size: int) -> tuple[int, int] | None:
    if not range_header or not range_header.startswith("bytes="):
        return None
    value = range_header.removeprefix("bytes=")
    start_text, _, end_text = value.partition("-")
    if not start_text and not end_text:
        raise AppError("INVALID_RANGE", "Range 头格式无效", status.HTTP_416_RANGE_NOT_SATISFIABLE)
    try:
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
        else:
            suffix_size = int(end_text)
            start = max(file_size - suffix_size, 0)
            end = file_size - 1
    except ValueError as exc:
        raise AppError(
            "INVALID_RANGE",
            "Range 头格式无效",
            status.HTTP_416_RANGE_NOT_SATISFIABLE,
        ) from exc
    if not start_text and suffix_size <= 0:
        raise AppError("INVALID_RANGE", "Range 头格式无效", status.HTTP_416_RANGE_NOT_SATISFIABLE)
    if start_text and start < 0:
        raise AppError("INVALID_RANGE", "Range 头格式无效", status.HTTP_416_RANGE_NOT_SATISFIABLE)
    if start_text and end_text and end < 0:
        raise AppError("INVALID_RANGE", "Range 头格式无效", status.HTTP_416_RANGE_NOT_SATISFIABLE)
    if start < 0 or end < start or start >= file_size:
        raise AppError("INVALID_RANGE", "Range 超出文件范围", status.HTTP_416_RANGE_NOT_SATISFIABLE)
    return start, min(end, file_size - 1)


def iter_file_range(path: Path, start: int, end: int) -> Iterator[bytes]:
    with path.open("rb") as file:
        file.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = file.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def stream_file_response(
    db: Session,
    file_id: str,
    current_user: User,
    range_header: str | None,
):
    file = get_file_with_task_access(db, file_id, current_user)
    path = safe_original_path(file.task_id, file.stored_name)
    if not path.is_file():
        raise AppError("TASK_NOT_FOUND", "文件不存在", status.HTTP_404_NOT_FOUND)

    file_size = path.stat().st_size
    media_type = file.mime_type or "application/octet-stream"
    byte_range = parse_range_header(range_header, file_size)
    if byte_range is None:
        return FileResponse(
            path,
            media_type=media_type,
            filename=file.original_name,
            headers={"Accept-Ranges": "bytes"},
        )

    start, end = byte_range
    return StreamingResponse(
        iter_file_range(path, start, end),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=media_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(end - start + 1),
        },
    )


def file_preview(db: Session, file_id: str, current_user: User) -> dict:
    file = get_file_with_task_access(db, file_id, current_user)
    data = serialize_file(file)
    data.update({"preview_available": False, "preview": None})
    return data
