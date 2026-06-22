from app.database import SessionLocal
from app.config import settings
from app.constants import SKILL_STATUS_ERROR
from app.models import SkillConfig
from app.skills.registry import check_skill_health, get_skill, is_enabled, registered_skill_ids
from app.utils.health_details import redact_health_detail


def test_registry_contains_seven_builtin_skills():
    assert registered_skill_ids() == [
        "document_parse",
        "image_ocr",
        "audio_transcribe",
        "video_parse",
        "intelligence_extract",
        "conflict_detect",
        "report_generate",
    ]
    assert get_skill("document_parse").manifest.id == "document_parse"


def test_is_enabled_reads_database_config():
    with SessionLocal() as db:
        config = db.get(SkillConfig, "image_ocr")
        config.enabled = False
        db.commit()

        assert is_enabled(db, "image_ocr") is False
        assert is_enabled(db, "document_parse") is True


def test_real_mode_health_requires_local_ocr_and_asr_model_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "ocr_model_dir", str(tmp_path / "missing-ocr"), raising=False)
    monkeypatch.setattr(settings, "asr_model_dir", str(tmp_path / "missing-asr"), raising=False)

    with SessionLocal() as db:
        ocr = check_skill_health(db, "image_ocr")
        asr = check_skill_health(db, "audio_transcribe")

    assert ocr["last_status"] == SKILL_STATUS_ERROR
    assert ocr["last_error"] == "模型目录未就绪"
    assert str(tmp_path) not in ocr["last_error"]
    assert asr["last_status"] == SKILL_STATUS_ERROR
    assert asr["last_error"] == "模型目录未就绪"
    assert str(tmp_path) not in asr["last_error"]

    with SessionLocal() as db:
        assert str(tmp_path) not in db.get(SkillConfig, "image_ocr").last_error
        assert str(tmp_path) not in db.get(SkillConfig, "audio_transcribe").last_error


def test_health_detail_redacts_sensitive_settings(monkeypatch, tmp_path):
    ocr_dir = tmp_path / "private-ocr"
    asr_dir = tmp_path / "private-asr"
    monkeypatch.setattr(settings, "ocr_model_dir", str(ocr_dir), raising=False)
    monkeypatch.setattr(settings, "asr_model_dir", str(asr_dir), raising=False)
    monkeypatch.setattr(settings, "local_llm_base_url", "http://secret-llm.local/v1", raising=False)
    monkeypatch.setattr(settings, "local_llm_api_key", "private-api-key", raising=False)

    detail = redact_health_detail(
        f"{settings.data_root_path} {ocr_dir} {asr_dir} "
        f"{settings.secret_key} {settings.local_llm_base_url} {settings.local_llm_api_key}"
    )

    assert str(settings.data_root_path) not in detail
    assert str(ocr_dir) not in detail
    assert str(asr_dir) not in detail
    assert settings.secret_key not in detail
    assert settings.local_llm_base_url not in detail
    assert settings.local_llm_api_key not in detail
    assert len(detail) <= 160
