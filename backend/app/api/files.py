from fastapi import APIRouter, Depends, File, Header, UploadFile, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models import User
from app.services import storage_service

router = APIRouter(tags=["files"])


@router.get("/tasks/{task_id}/files")
def list_files(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return {"data": storage_service.list_task_files(db, task_id, current_user), "message": "ok"}


@router.post("/tasks/{task_id}/files", status_code=status.HTTP_201_CREATED)
async def upload_files(
    task_id: str,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    uploaded = await storage_service.upload_task_files(db, task_id, files, current_user)
    return {"data": uploaded, "message": "ok"}


@router.delete("/files/{file_id}")
def delete_file(
    file_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    storage_service.delete_file(db, file_id, current_user)
    return {"data": {"id": file_id}, "message": "ok"}


@router.get("/files/{file_id}/stream")
def stream_file(
    file_id: str,
    range_header: str | None = Header(default=None, alias="Range"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return storage_service.stream_file_response(db, file_id, current_user, range_header)


@router.get("/files/{file_id}/preview")
def preview_file(
    file_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return {"data": storage_service.file_preview(db, file_id, current_user), "message": "ok"}
