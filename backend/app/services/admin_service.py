from datetime import datetime
from typing import Any

from fastapi import status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.constants import ROLE_ADMIN
from app.models import User
from app.schemas import AdminUserCreate, AdminUserUpdate, AppError
from app.services.audit_service import record_audit
from app.services.auth_service import hash_password


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def serialize_admin_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": _isoformat(user.created_at),
    }


def _active_admin_count(db: Session) -> int:
    return (
        db.query(func.count(User.id))
        .filter(User.role == ROLE_ADMIN, User.is_active.is_(True))
        .scalar()
        or 0
    )


def list_users(db: Session) -> list[dict[str, Any]]:
    users = db.query(User).order_by(User.created_at.asc()).all()
    return [serialize_admin_user(user) for user in users]


def create_user(db: Session, payload: AdminUserCreate, current_user: User) -> dict[str, Any]:
    existing = db.query(User).filter(User.username == payload.username).one_or_none()
    if existing is not None:
        raise AppError("USER_ALREADY_EXISTS", "用户名已存在", status.HTTP_409_CONFLICT)

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    record_audit(
        db,
        user_id=current_user.id,
        action="user_created",
        resource_type="user",
        resource_id=user.id,
        detail={"username": user.username, "role": user.role},
    )
    db.commit()
    db.refresh(user)
    return serialize_admin_user(user)


def update_user(
    db: Session,
    user_id: str,
    payload: AdminUserUpdate,
    current_user: User,
) -> dict[str, Any]:
    user = db.get(User, user_id)
    if user is None:
        raise AppError("USER_NOT_FOUND", "用户不存在", status.HTTP_404_NOT_FOUND)

    next_role = payload.role if payload.role is not None else user.role
    next_active = payload.is_active if payload.is_active is not None else user.is_active
    would_remove_active_admin = (
        user.role == ROLE_ADMIN
        and user.is_active
        and (next_role != ROLE_ADMIN or not next_active)
    )
    if would_remove_active_admin and _active_admin_count(db) <= 1:
        raise AppError(
            "LAST_ACTIVE_ADMIN",
            "至少需要保留一个启用的管理员",
            status.HTTP_409_CONFLICT,
        )
    if user.id == current_user.id and (next_role != ROLE_ADMIN or not next_active):
        raise AppError(
            "CANNOT_MODIFY_SELF",
            "管理员不能停用或降级当前账号",
            status.HTTP_409_CONFLICT,
        )

    changed_fields: list[str] = []
    if payload.is_active is not None and payload.is_active != user.is_active:
        user.is_active = payload.is_active
        changed_fields.append("is_active")
    if payload.role is not None and payload.role != user.role:
        user.role = payload.role
        changed_fields.append("role")
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
        changed_fields.append("password")

    if changed_fields:
        record_audit(
            db,
            user_id=current_user.id,
            action="user_updated",
            resource_type="user",
            resource_id=user.id,
            detail={
                "username": user.username,
                "changed_fields": changed_fields,
                "password_reset": "password" in changed_fields,
            },
        )
    db.commit()
    db.refresh(user)
    return serialize_admin_user(user)
