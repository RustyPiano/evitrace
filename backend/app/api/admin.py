from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_admin
from app.models import User
from app.schemas import AdminSkillUpdate, AdminUserCreate, AdminUserUpdate
from app.services import admin_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/health")
def admin_health(_: User = Depends(require_admin)) -> dict:
    return {"data": {"status": "ok"}, "message": "ok"}


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
