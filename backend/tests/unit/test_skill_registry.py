from app.database import SessionLocal
from app.models import SkillConfig
from app.skills.registry import get_skill, is_enabled, registered_skill_ids


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
