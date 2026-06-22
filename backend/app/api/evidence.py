from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models import User
from app.services import result_service

router = APIRouter(tags=["evidence"])


@router.get("/tasks/{task_id}/evidence")
def list_evidence(
    task_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1),
    file_id: str | None = None,
    modality: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return {
        "data": result_service.list_task_evidence(
            db,
            task_id,
            current_user,
            page=page,
            page_size=page_size,
            file_id=file_id,
            modality=modality,
        ),
        "message": "ok",
    }


@router.get("/tasks/{task_id}/evidence/index")
def list_evidence_index(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return {"data": result_service.list_task_evidence_index(db, task_id, current_user), "message": "ok"}


@router.get("/evidence/{evidence_id}")
def get_evidence(
    evidence_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return {"data": result_service.get_evidence_detail(db, evidence_id, current_user), "message": "ok"}


@router.get("/evidence/{evidence_id}/source")
def get_evidence_source(
    evidence_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return {"data": result_service.evidence_source(db, evidence_id, current_user), "message": "ok"}


@router.get("/evidence/{evidence_id}/frame")
def get_evidence_frame(
    evidence_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return result_service.frame_file_response(db, evidence_id, current_user)
