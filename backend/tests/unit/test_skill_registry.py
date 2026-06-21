from app.database import SessionLocal
from app.config import settings
from app.constants import SKILL_STATUS_ERROR
from app.models import SkillConfig
from app.skills.registry import check_skill_health, get_skill, is_enabled, registered_skill_ids


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
    assert "OCR_MODEL_DIR" in ocr["last_error"]
    assert asr["last_status"] == SKILL_STATUS_ERROR
    assert "ASR_MODEL_DIR" in asr["last_error"]
