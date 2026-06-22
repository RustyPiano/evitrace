import json
import re

from tests.conftest import login_headers


def test_system_mode_requires_login(client):
    response = client.get("/api/v1/system/mode")

    assert response.status_code == 401


def test_system_mode_returns_run_mode_for_logged_in_user(client, create_user):
    create_user("analyst")
    headers = login_headers(client, "analyst", "password")

    response = client.get("/api/v1/system/mode", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "ok"
    data = body["data"]
    assert data["mode"] in {"real", "mock", "hybrid"}
    assert data["mode_label"] in {"本地真实", "演示Fixture", "混合模式"}
    assert {"mock_llm", "mock_media", "mock_vision", "llm", "vision", "ocr", "asr", "skills"} <= set(data)
    assert isinstance(data["skills"], list)
    serialized = json.dumps(data, ensure_ascii=False)
    assert "sk-" not in serialized
    assert "base_url" not in serialized
    assert "api_key" not in serialized
    assert re.search(r"https?://", serialized) is None
