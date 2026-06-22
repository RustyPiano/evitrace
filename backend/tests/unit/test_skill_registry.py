from app.database import SessionLocal
from app.config import settings
from app.constants import SKILL_STATUS_ERROR
from app.models import SkillConfig
from app.skills.registry import check_skill_health, get_skill, is_enabled, registered_skill_ids
from app.utils.health_details import redact_health_detail


def test_registry_contains_eight_builtin_skills():
    assert registered_skill_ids() == [
        "document_parse",
        "image_ocr",
        "audio_transcribe",
        "video_parse",
        "visual_understand",
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
    monkeypatch.setattr(settings, "mock_media", None)
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


def test_registry_media_health_uses_mock_media_when_llm_is_real(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_media", True)
    monkeypatch.setattr(settings, "mock_vision", None, raising=False)
    monkeypatch.setattr(settings, "vlm_base_url", None, raising=False)
    monkeypatch.setattr(settings, "vlm_api_key", None, raising=False)
    monkeypatch.setattr(settings, "vlm_model", None, raising=False)
    monkeypatch.setattr(settings, "ocr_model_dir", str(tmp_path / "missing-ocr"), raising=False)
    monkeypatch.setattr(settings, "asr_model_dir", str(tmp_path / "missing-asr"), raising=False)

    with SessionLocal() as db:
        ocr = check_skill_health(db, "image_ocr")
        asr = check_skill_health(db, "audio_transcribe")
        video = check_skill_health(db, "video_parse")
        visual = check_skill_health(db, "visual_understand")

    assert ocr["last_error"] is None
    assert asr["last_error"] is None
    assert video["last_error"] is None
    assert visual["last_error"] is None
    assert visual["last_status"] == "skipped"


def test_registry_media_health_uses_http_services_before_local_models(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_media", None)
    monkeypatch.setattr(settings, "ocr_base_url", "http://ocr.local", raising=False)
    monkeypatch.setattr(settings, "asr_base_url", "http://asr.local", raising=False)
    monkeypatch.setattr(settings, "ocr_model_dir", str(tmp_path / "missing-ocr"), raising=False)
    monkeypatch.setattr(settings, "asr_model_dir", str(tmp_path / "missing-asr"), raising=False)
    calls: list[tuple[str, str]] = []

    def fake_media_health(base_url, *, service_name):
        calls.append((base_url, service_name))
        return {"status": "healthy", "message": f"{service_name} HTTP service ok"}

    monkeypatch.setattr("app.skills.registry.check_media_health", fake_media_health)

    with SessionLocal() as db:
        ocr = check_skill_health(db, "image_ocr")
        asr = check_skill_health(db, "audio_transcribe")

    assert calls == [("http://ocr.local", "OCR"), ("http://asr.local", "ASR")]
    assert ocr["last_status"] == "healthy"
    assert ocr["last_error"] is None
    assert asr["last_status"] == "healthy"
    assert asr["last_error"] is None


def test_registry_http_media_health_error_is_redacted(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_media", None)
    monkeypatch.setattr(settings, "ocr_base_url", "http://secret-ocr.local", raising=False)

    def fake_media_health(_base_url, *, service_name):
        return {
            "status": "unavailable",
            "message": f"{service_name} probe failed at {settings.ocr_base_url}",
        }

    monkeypatch.setattr("app.skills.registry.check_media_health", fake_media_health)

    with SessionLocal() as db:
        ocr = check_skill_health(db, "image_ocr")

    assert ocr["last_status"] == SKILL_STATUS_ERROR
    assert ocr["last_error"] == "OCR probe failed at [ocr-base-url]"


def test_visual_understand_health_is_real_when_vlm_configured_even_if_media_is_mocked(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_media", True)
    monkeypatch.setattr(settings, "mock_vision", None, raising=False)
    monkeypatch.setattr(settings, "vlm_base_url", "https://vlm.example/v1", raising=False)
    monkeypatch.setattr(settings, "vlm_api_key", "private-vlm-api-key", raising=False)
    monkeypatch.setattr(settings, "vlm_model", "qwen-vl", raising=False)

    with SessionLocal() as db:
        visual = check_skill_health(db, "visual_understand")

    assert visual["last_status"] == "healthy"
    assert visual["last_error"] is None


def test_visual_understand_real_mode_health_requires_vlm_config(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_media", True)
    monkeypatch.setattr(settings, "mock_vision", False, raising=False)
    monkeypatch.setattr(settings, "vlm_base_url", None, raising=False)
    monkeypatch.setattr(settings, "vlm_api_key", None, raising=False)
    monkeypatch.setattr(settings, "vlm_model", None, raising=False)

    with SessionLocal() as db:
        visual = check_skill_health(db, "visual_understand")

    assert visual["last_status"] == SKILL_STATUS_ERROR
    assert visual["last_error"] == "VLM 配置未就绪"


def test_health_detail_redacts_sensitive_settings(monkeypatch, tmp_path):
    ocr_dir = tmp_path / "private-ocr"
    asr_dir = tmp_path / "private-asr"
    monkeypatch.setattr(settings, "ocr_model_dir", str(ocr_dir), raising=False)
    monkeypatch.setattr(settings, "asr_model_dir", str(asr_dir), raising=False)
    monkeypatch.setattr(settings, "ocr_base_url", "http://secret-ocr.local", raising=False)
    monkeypatch.setattr(settings, "asr_base_url", "http://secret-asr.local", raising=False)
    monkeypatch.setattr(settings, "local_llm_base_url", "http://secret-llm.local/v1", raising=False)
    monkeypatch.setattr(settings, "local_llm_api_key", "private-api-key", raising=False)
    monkeypatch.setattr(settings, "vlm_base_url", "https://secret-vlm.local/v1", raising=False)
    monkeypatch.setattr(settings, "vlm_api_key", "private-vlm-api-key", raising=False)

    detail = redact_health_detail(
        f"{settings.data_root_path} {ocr_dir} {asr_dir} "
        f"{settings.ocr_base_url} {settings.asr_base_url} "
        f"{settings.secret_key} {settings.local_llm_base_url} {settings.local_llm_api_key} "
        f"{settings.vlm_base_url} {settings.vlm_api_key}"
    )

    assert str(settings.data_root_path) not in detail
    assert str(ocr_dir) not in detail
    assert str(asr_dir) not in detail
    assert settings.ocr_base_url not in detail
    assert settings.asr_base_url not in detail
    assert settings.secret_key not in detail
    assert settings.local_llm_base_url not in detail
    assert settings.local_llm_api_key not in detail
    assert settings.vlm_base_url not in detail
    assert settings.vlm_api_key not in detail
    assert len(detail) <= 160


def test_health_detail_redacts_short_vlm_api_key(monkeypatch):
    monkeypatch.setattr(settings, "vlm_api_key", "vlm123", raising=False)

    detail = redact_health_detail(f"VLM failed with key {settings.vlm_api_key}")

    assert "[vlm-api-key]" in detail
    assert "vlm123" not in detail
