from app.config import settings
from app.database import SessionLocal
from app.services import admin_service


def test_admin_component_health_uses_split_mock_flags(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_llm", False)
    monkeypatch.setattr(settings, "mock_media", True)
    monkeypatch.setattr(settings, "mock_vision", None, raising=False)
    monkeypatch.setattr(settings, "vlm_base_url", None, raising=False)
    monkeypatch.setattr(settings, "vlm_api_key", None, raising=False)
    monkeypatch.setattr(settings, "vlm_model", None, raising=False)
    monkeypatch.setattr(admin_service, "ping_local_llm", lambda: {"status": "healthy"})

    with SessionLocal() as db:
        components = admin_service.component_health(db)["components"]

    by_name = {item["component"]: item for item in components}
    assert by_name["llm"]["status"] == "healthy"
    assert by_name["ffmpeg"]["status"] == "skipped"
    assert by_name["ocr"]["status"] == "skipped"
    assert by_name["asr"]["status"] == "skipped"
    assert by_name["vlm"]["status"] == "skipped"


def test_admin_component_health_reports_vlm_config_when_vision_forced_real(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_llm", True)
    monkeypatch.setattr(settings, "mock_media", True)
    monkeypatch.setattr(settings, "mock_vision", False, raising=False)
    monkeypatch.setattr(settings, "vlm_base_url", None, raising=False)
    monkeypatch.setattr(settings, "vlm_api_key", None, raising=False)
    monkeypatch.setattr(settings, "vlm_model", None, raising=False)

    with SessionLocal() as db:
        components = admin_service.component_health(db)["components"]

    by_name = {item["component"]: item for item in components}
    assert by_name["vlm"]["status"] == "unavailable"
    assert by_name["vlm"]["detail"] == "VLM configuration not ready"


def test_admin_component_health_reports_vlm_ready_when_configured_with_mock_media(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_llm", True)
    monkeypatch.setattr(settings, "mock_media", True)
    monkeypatch.setattr(settings, "mock_vision", None, raising=False)
    monkeypatch.setattr(settings, "vlm_base_url", "https://vlm.example/v1", raising=False)
    monkeypatch.setattr(settings, "vlm_api_key", "private-vlm-api-key", raising=False)
    monkeypatch.setattr(settings, "vlm_model", "qwen-vl", raising=False)

    with SessionLocal() as db:
        components = admin_service.component_health(db)["components"]

    by_name = {item["component"]: item for item in components}
    assert by_name["ffmpeg"]["status"] == "skipped"
    assert by_name["ocr"]["status"] == "skipped"
    assert by_name["asr"]["status"] == "skipped"
    assert by_name["vlm"]["status"] == "healthy"
