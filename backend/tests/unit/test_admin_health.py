from app.config import settings
from app.database import SessionLocal
from app.services import admin_service


def test_admin_component_health_uses_split_mock_flags(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_llm", False)
    monkeypatch.setattr(settings, "mock_media", True)
    monkeypatch.setattr(admin_service, "ping_local_llm", lambda: {"status": "healthy"})

    with SessionLocal() as db:
        components = admin_service.component_health(db)["components"]

    by_name = {item["component"]: item for item in components}
    assert by_name["llm"]["status"] == "healthy"
    assert by_name["ffmpeg"]["status"] == "skipped"
    assert by_name["ocr"]["status"] == "skipped"
    assert by_name["asr"]["status"] == "skipped"
