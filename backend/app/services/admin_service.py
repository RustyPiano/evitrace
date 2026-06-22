import importlib.util
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import ROLE_ADMIN
from app.models import AuditLog, SkillConfig, User
from app.schemas import AdminSkillUpdate, AdminUserCreate, AdminUserUpdate, AppError
from app.services.audit_service import record_audit
from app.services.auth_service import hash_password
from app.services.llm_client import ping_local_llm
from app.skills.registry import check_skill_health as run_skill_health
from app.skills.registry import serialize_skill_config, set_skill_enabled
from app.utils.health_details import redact_health_detail


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


def list_skills(db: Session) -> list[dict[str, Any]]:
    skills = db.query(SkillConfig).order_by(SkillConfig.skill_id.asc()).all()
    return [serialize_skill_config(skill) for skill in skills]


def update_skill(
    db: Session,
    skill_id: str,
    payload: AdminSkillUpdate,
    current_user: User,
) -> dict[str, Any]:
    config = set_skill_enabled(db, skill_id, payload.enabled)
    record_audit(
        db,
        user_id=current_user.id,
        action="skill_updated",
        resource_type="skill",
        resource_id=config.skill_id,
        detail={"enabled": config.enabled},
    )
    db.commit()
    db.refresh(config)
    return serialize_skill_config(config)


def check_skill_health(db: Session, skill_id: str) -> dict[str, Any]:
    return run_skill_health(db, skill_id)


def component_health(db: Session) -> dict[str, Any]:
    return {
        "components": [
            _database_health(db),
            _disk_health(),
            _llm_health(),
            _ffmpeg_health(),
            _ocr_health(),
            _asr_health(),
        ]
    }


def list_audit_logs(db: Session, *, page: int, page_size: int) -> dict[str, Any]:
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), 100)
    query = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    total = query.count()
    rows = query.offset((safe_page - 1) * safe_page_size).limit(safe_page_size).all()
    user_ids = {row.user_id for row in rows if row.user_id}
    users = {}
    if user_ids:
        users = {
            user.id: user.username
            for user in db.query(User).filter(User.id.in_(user_ids)).all()
        }
    return {
        "items": [_serialize_audit_log(row, users.get(row.user_id)) for row in rows],
        "total": total,
        "page": safe_page,
        "page_size": safe_page_size,
    }


def _database_health(db: Session) -> dict[str, str]:
    try:
        db.execute(func.count(User.id).select())
    except Exception:
        return _health_item("database", "unavailable", "database probe failed")
    return _health_item("database", "healthy", "database probe ok")


def _disk_health() -> dict[str, str]:
    try:
        settings.data_root_path.mkdir(parents=True, exist_ok=True)
        probe = settings.data_root_path / ".healthcheck"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        free_mb = shutil.disk_usage(settings.data_root_path).free // (1024 * 1024)
    except Exception:
        return _health_item("disk", "unavailable", "data directory is not writable")
    return _health_item("disk", "healthy", f"writable, about {free_mb} MB free")


def _llm_health() -> dict[str, str]:
    if settings.mock_ai:
        return _health_item("llm", "skipped", "MOCK_AI enabled")
    health = ping_local_llm()
    if health.get("status") == "healthy":
        return _health_item("llm", "healthy", "local model probe ok")
    return _health_item("llm", "unavailable", health.get("message") or health.get("code"))


def _ffmpeg_health() -> dict[str, str]:
    if shutil.which("ffmpeg") is None:
        return _health_item("ffmpeg", "unavailable", "ffmpeg executable not found")
    return _health_item("ffmpeg", "healthy", "ffmpeg executable available")


def _ocr_health() -> dict[str, str]:
    if settings.mock_ai:
        return _health_item("ocr", "skipped", "MOCK_AI enabled")
    if importlib.util.find_spec("paddleocr") is None:
        return _health_item("ocr", "unavailable", "paddleocr dependency not installed")
    if not _configured_directory_ready(settings.ocr_model_dir):
        return _health_item("ocr", "unavailable", "OCR model directory not ready")
    return _health_item("ocr", "healthy", "OCR dependency and model directory ready")


def _asr_health() -> dict[str, str]:
    if settings.mock_ai:
        return _health_item("asr", "skipped", "MOCK_AI enabled")
    if importlib.util.find_spec("faster_whisper") is None:
        return _health_item("asr", "unavailable", "faster_whisper dependency not installed")
    if not _configured_directory_ready(settings.asr_model_dir):
        return _health_item("asr", "unavailable", "ASR model directory not ready")
    return _health_item("asr", "healthy", "ASR dependency and model directory ready")


def _configured_directory_ready(value: str | None) -> bool:
    if not value:
        return False
    return Path(value).expanduser().is_dir()


def _health_item(component: str, status_value: str, detail: str) -> dict[str, str]:
    return {
        "component": component,
        "status": status_value,
        "detail": redact_health_detail(detail),
    }


def _serialize_audit_log(row: AuditLog, username: str | None) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "username": username,
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "detail": _redact_detail(_json_detail(row.detail_json)),
        "created_at": _isoformat(row.created_at),
    }


def _json_detail(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _redact_detail(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[redacted]" if _sensitive_key(key) else _redact_detail(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_detail(item) for item in value]
    return value


def _sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in ("password", "secret", "token", "api_key"))
