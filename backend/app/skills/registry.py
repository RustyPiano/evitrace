import importlib.util
import shutil
from typing import Any

from fastapi import status
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import SKILL_STATUS_ERROR, SKILL_STATUS_HEALTHY, SKILL_STATUS_UNKNOWN
from app.models import SkillConfig
from app.schemas import AppError

from .audio_transcribe import AudioTranscribeSkill, resolve_asr_model_path
from .conflict_detect import ConflictDetectSkill
from .document_parse import DocumentParseSkill
from .image_ocr import ImageOcrSkill, resolve_ocr_model_dirs
from .intelligence_extract import IntelligenceExtractSkill
from .report_generate import ReportGenerateSkill
from .video_parse import VideoParseSkill


document_parse = DocumentParseSkill()
image_ocr = ImageOcrSkill()
audio_transcribe = AudioTranscribeSkill()
video_parse = VideoParseSkill()
intelligence_extract = IntelligenceExtractSkill()
conflict_detect = ConflictDetectSkill()
report_generate = ReportGenerateSkill()

SKILL_REGISTRY = {
    "document_parse": document_parse,
    "image_ocr": image_ocr,
    "audio_transcribe": audio_transcribe,
    "video_parse": video_parse,
    "intelligence_extract": intelligence_extract,
    "conflict_detect": conflict_detect,
    "report_generate": report_generate,
}

SKILL_MANIFESTS = [skill.manifest for skill in SKILL_REGISTRY.values()]


def registered_skill_ids() -> list[str]:
    return list(SKILL_REGISTRY.keys())


def get_skill(skill_id: str):
    try:
        return SKILL_REGISTRY[skill_id]
    except KeyError as exc:
        raise AppError("SKILL_NOT_FOUND", "Skill 不存在", status.HTTP_404_NOT_FOUND) from exc


def get_manifest(skill_id: str) -> SkillManifest:
    return get_skill(skill_id).manifest


def is_enabled(db: Session, skill_id: str) -> bool:
    config = db.get(SkillConfig, skill_id)
    if config is not None:
        return config.enabled
    return get_manifest(skill_id).enabled_by_default


def sync_skill_configs(db: Session) -> None:
    for manifest in SKILL_MANIFESTS:
        existing = db.get(SkillConfig, manifest.id)
        if existing is None:
            db.add(
                SkillConfig(
                    skill_id=manifest.id,
                    name=manifest.name,
                    version=manifest.version,
                    enabled=manifest.enabled_by_default,
                    required=manifest.required,
                    last_status=SKILL_STATUS_UNKNOWN,
                )
            )
            continue

        existing.name = manifest.name
        existing.version = manifest.version
        existing.required = manifest.required

    db.commit()


def serialize_skill_config(config: SkillConfig) -> dict[str, Any]:
    return {
        "skill_id": config.skill_id,
        "name": config.name,
        "version": config.version,
        "enabled": config.enabled,
        "required": config.required,
        "last_status": config.last_status,
        "last_error": config.last_error,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


def set_skill_enabled(db: Session, skill_id: str, enabled: bool) -> SkillConfig:
    manifest = get_manifest(skill_id)
    config = db.get(SkillConfig, skill_id)
    if config is None:
        config = SkillConfig(
            skill_id=manifest.id,
            name=manifest.name,
            version=manifest.version,
            enabled=manifest.enabled_by_default,
            required=manifest.required,
            last_status=SKILL_STATUS_UNKNOWN,
        )
        db.add(config)
        db.flush()

    if manifest.required and not enabled:
        raise AppError(
            "REQUIRED_SKILL_CANNOT_DISABLE",
            "必需 Skill 不可停用",
            status.HTTP_409_CONFLICT,
        )

    config.enabled = enabled
    return config


def _require_import(module_name: str) -> None:
    if importlib.util.find_spec(module_name) is None:
        raise RuntimeError(f"missing dependency: {module_name}")


def check_skill_health(db: Session, skill_id: str) -> dict[str, Any]:
    manifest = get_manifest(skill_id)
    config = db.get(SkillConfig, skill_id)
    if config is None:
        sync_skill_configs(db)
        config = db.get(SkillConfig, skill_id)

    try:
        if skill_id == "document_parse":
            _require_import("fitz")
            _require_import("docx")
            _require_import("charset_normalizer")
        elif skill_id == "image_ocr" and not settings.mock_ai:
            resolve_ocr_model_dirs()
            _require_import("paddleocr")
        elif skill_id == "audio_transcribe" and not settings.mock_ai:
            resolve_asr_model_path()
            _require_import("faster_whisper")
        elif skill_id == "video_parse" and not settings.mock_ai:
            if shutil.which("ffmpeg") is None:
                raise RuntimeError("missing executable: ffmpeg")
            resolve_ocr_model_dirs()
            resolve_asr_model_path()
            _require_import("paddleocr")
            _require_import("faster_whisper")
        elif skill_id in {"intelligence_extract", "report_generate"} and not settings.mock_ai:
            from app.services.llm_client import ping_local_llm

            health = ping_local_llm()
            if health.get("status") != "healthy":
                raise RuntimeError(health.get("message") or health.get("code") or "local llm unavailable")
        config.last_status = SKILL_STATUS_HEALTHY
        config.last_error = None
    except Exception as exc:
        config.last_status = SKILL_STATUS_ERROR
        config.last_error = str(exc)

    db.commit()
    db.refresh(config)
    return serialize_skill_config(config)
