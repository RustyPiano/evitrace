import base64
import json

import httpx
import pytest

from app.config import settings
from app.services.vision_client import VisionClient


def test_vision_client_sends_image_as_data_url_chat_content(tmp_path):
    image_path = tmp_path / "frame.png"
    image_bytes = b"\x89PNG\r\n\x1a\nfixture"
    image_path.write_bytes(image_bytes)
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        payload = json.loads(request.content)
        seen["payload"] = payload
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "画面中有车辆和人员活动。"}}]},
        )

    client = VisionClient(
        mock_media=False,
        base_url="http://vlm.local/v1",
        api_key="test-key",
        model="qwen-vl",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    caption = client.describe_image(image_path, "描述画面")

    assert caption == "画面中有车辆和人员活动。"
    assert seen["url"] == "http://vlm.local/v1/chat/completions"
    assert seen["auth"] == "Bearer test-key"
    payload = seen["payload"]
    assert payload["model"] == "qwen-vl"
    content = payload["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "描述画面"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == (
        "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    )


def test_vision_client_real_mode_requires_vlm_endpoint_and_model(tmp_path):
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"jpeg")
    client = VisionClient(mock_media=False, base_url="", model="")

    with pytest.raises(RuntimeError, match="VLM_BASE_URL.*VLM_MODEL"):
        client.describe_image(image_path, "描述画面")


def test_vision_client_defaults_to_vision_mock_flag_not_media_mock(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_media", True)
    monkeypatch.setattr(settings, "mock_vision", None, raising=False)
    monkeypatch.setattr(settings, "vlm_base_url", "http://vlm.local/v1", raising=False)
    monkeypatch.setattr(settings, "vlm_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "vlm_model", "qwen-vl", raising=False)

    client = VisionClient()

    assert client.mock_vision is False


def test_vision_client_mock_mode_does_not_call_network(tmp_path):
    image_path = tmp_path / "mock_frame_000002.png"
    image_path.write_bytes(b"png")

    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("mock mode must not call network")

    client = VisionClient(
        mock_media=True,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    caption = client.describe_image(image_path, "描述画面")

    assert "MOCK 画面描述" in caption
    assert "mock_frame_000002.png" in caption
