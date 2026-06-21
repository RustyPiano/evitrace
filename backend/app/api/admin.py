from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_admin
from app.models import User
from app.schemas import AdminSkillUpdate, AdminUserCreate, AdminUserUpdate
from app.services import admin_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/health")
def admin_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    return {"data": admin_service.component_health(db), "message": "ok"}


@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    return {"data": admin_service.list_users(db), "message": "ok"}


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AdminUserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    return {"data": admin_service.create_user(db, payload, current_user), "message": "ok"}


@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    return {
        "data": admin_service.update_user(db, user_id, payload, current_user),
        "message": "ok",
    }


@router.get("/skills")
def list_skills(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    return {"data": admin_service.list_skills(db), "message": "ok"}


@router.patch("/skills/{skill_id}")
def update_skill(
    skill_id: str,
    payload: AdminSkillUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    return {
        "data": admin_service.update_skill(db, skill_id, payload, current_user),
        "message": "ok",
    }


@router.post("/skills/{skill_id}/health")
def check_skill_health(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    return {
        "data": admin_service.check_skill_health(db, skill_id),
        "message": "ok",
    }


@router.get("/audit-logs")
def list_audit_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    return {
        "data": admin_service.list_audit_logs(db, page=page, page_size=page_size),
        "message": "ok",
    }
