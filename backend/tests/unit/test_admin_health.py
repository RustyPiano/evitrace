from app.config import settings
from app.database import SessionLocal
from app.services import admin_service
from app.skills import audio_transcribe as audio_transcribe_module
from app.skills import image_ocr as image_ocr_module


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


def test_admin_component_health_probes_http_media_services_when_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_llm", True)
    monkeypatch.setattr(settings, "mock_media", False)
    monkeypatch.setattr(settings, "mock_vision", True, raising=False)
    monkeypatch.setattr(settings, "ocr_base_url", "http://ocr.local", raising=False)
    monkeypatch.setattr(settings, "asr_base_url", "http://asr.local", raising=False)
    monkeypatch.setattr(settings, "ocr_model_dir", str(tmp_path / "missing-ocr"), raising=False)
    monkeypatch.setattr(settings, "asr_model_dir", str(tmp_path / "missing-asr"), raising=False)
    calls: list[tuple[str, str]] = []

    def fake_media_health(base_url, *, service_name):
        calls.append((base_url, service_name))
        return {"status": "healthy", "message": f"{service_name} HTTP service ok", "warmed": True}

    monkeypatch.setattr(admin_service, "check_media_health", fake_media_health)

    with SessionLocal() as db:
        components = admin_service.component_health(db)["components"]

    by_name = {item["component"]: item for item in components}
    assert calls == [("http://ocr.local", "OCR"), ("http://asr.local", "ASR")]
    assert by_name["ocr"]["status"] == "healthy"
    assert by_name["ocr"]["detail"] == "OCR HTTP service ok"
    assert by_name["asr"]["status"] == "healthy"
    assert by_name["asr"]["detail"] == "ASR HTTP service ok"


def test_admin_component_health_reports_http_media_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_llm", True)
    monkeypatch.setattr(settings, "mock_media", False)
    monkeypatch.setattr(settings, "mock_vision", True, raising=False)
    monkeypatch.setattr(settings, "ocr_base_url", "http://ocr.local", raising=False)
    monkeypatch.setattr(settings, "asr_base_url", None, raising=False)

    def fake_media_health(_base_url, *, service_name):
        return {"status": "unavailable", "message": f"{service_name} HTTP service returned HTTP 503"}

    monkeypatch.setattr(admin_service, "check_media_health", fake_media_health)

    with SessionLocal() as db:
        components = admin_service.component_health(db)["components"]

    by_name = {item["component"]: item for item in components}
    assert by_name["ocr"]["status"] == "unavailable"
    assert by_name["ocr"]["detail"] == "OCR HTTP service returned HTTP 503"


def test_admin_component_health_resolves_relative_local_model_paths_like_skills(monkeypatch, tmp_path):
    ocr_root = tmp_path / "models" / "ocr"
    (ocr_root / "det").mkdir(parents=True)
    (ocr_root / "rec").mkdir()
    asr_root = tmp_path / "models" / "asr"
    (asr_root / "small").mkdir(parents=True)

    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_llm", True)
    monkeypatch.setattr(settings, "mock_media", False)
    monkeypatch.setattr(settings, "mock_vision", True, raising=False)
    monkeypatch.setattr(settings, "ocr_base_url", None, raising=False)
    monkeypatch.setattr(settings, "asr_base_url", None, raising=False)
    monkeypatch.setattr(settings, "ocr_model_dir", "models/ocr", raising=False)
    monkeypatch.setattr(settings, "asr_model_dir", "models/asr", raising=False)
    monkeypatch.setattr(settings, "asr_model_size", "small", raising=False)
    monkeypatch.setattr(image_ocr_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(audio_transcribe_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(admin_service.importlib.util, "find_spec", lambda name: object())

    with SessionLocal() as db:
        components = admin_service.component_health(db)["components"]

    by_name = {item["component"]: item for item in components}
    assert by_name["ocr"]["status"] == "healthy"
    assert by_name["asr"]["status"] == "healthy"
