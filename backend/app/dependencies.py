from collections.abc import Generator

from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.constants import ROLE_ADMIN
from app.database import SessionLocal
from app.models import User
from app.schemas import AppError
from app.services.auth_service import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError("INVALID_CREDENTIALS", "未提供认证凭据", status.HTTP_401_UNAUTHORIZED)

    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not isinstance(user_id, str):
        raise AppError("INVALID_CREDENTIALS", "认证凭据无效", status.HTTP_401_UNAUTHORIZED)

    user = db.get(User, user_id)
    if user is None:
        raise AppError("INVALID_CREDENTIALS", "认证用户不存在", status.HTTP_401_UNAUTHORIZED)
    if not user.is_active:
        raise AppError("INACTIVE_USER", "用户已停用", status.HTTP_403_FORBIDDEN)
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != ROLE_ADMIN:
        raise AppError("FORBIDDEN", "无权限", status.HTTP_403_FORBIDDEN)
    return current_user
