from datetime import timedelta
from typing import Any

import bcrypt
import jwt
from fastapi import status
from jwt import PyJWTError
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import ROLE_ADMIN
from app.models import User, utc_now
from app.schemas import AppError
from app.services.audit_service import record_audit

JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user: User) -> str:
    expires_at = utc_now() + timedelta(hours=settings.access_token_expire_hours)
    payload: dict[str, Any] = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[JWT_ALGORITHM])
    except PyJWTError as exc:
        raise AppError(
            "INVALID_CREDENTIALS",
            "认证凭据无效或已过期",
            status.HTTP_401_UNAUTHORIZED,
        ) from exc


def authenticate_user(db: Session, username: str, password: str) -> User:
    user = db.query(User).filter(User.username == username).one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        record_audit(
            db,
            user_id=user.id if user else None,
            action="login_failed",
            resource_type="user",
            resource_id=user.id if user else None,
            detail={"username": username},
            commit=True,
        )
        raise AppError(
            "INVALID_CREDENTIALS",
            "用户名或密码错误",
            status.HTTP_401_UNAUTHORIZED,
        )

    if not user.is_active:
        record_audit(
            db,
            user_id=user.id,
            action="login_failed",
            resource_type="user",
            resource_id=user.id,
            detail={"username": username, "reason": "inactive_user"},
            commit=True,
        )
        raise AppError("INACTIVE_USER", "用户已停用", status.HTTP_403_FORBIDDEN)

    record_audit(
        db,
        user_id=user.id,
        action="login_success",
        resource_type="user",
        resource_id=user.id,
        detail={"username": username},
        commit=True,
    )
    return user


def seed_default_admin(db: Session) -> None:
    existing = db.query(User).filter(User.username == settings.first_admin_username).one_or_none()
    if existing is not None:
        return

    admin = User(
        username=settings.first_admin_username,
        password_hash=hash_password(settings.first_admin_password),
        role=ROLE_ADMIN,
        is_active=True,
    )
    db.add(admin)
    db.commit()
