import json

import httpx
import pytest

from app.services import media_client
from app.services.media_client import asr_audio, check_media_health, ocr_image


def test_ocr_image_posts_multipart_file_and_returns_results(tmp_path, monkeypatch):
    monkeypatch.setattr(media_client.settings, "media_timeout_sec", 42, raising=False)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"png-bytes")
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["content_type"] = request.headers.get("content-type")
        seen["body"] = request.content
        return httpx.Response(
            200,
            json={
                "filename": "screen.png",
                "width": 640,
                "height": 480,
                "count": 1,
                "results": [{"text": "坐标 42", "score": 0.93, "box": [1, 2, 30, 40]}],
            },
        )

    results = ocr_image(
        "http://ocr.local/",
        image_path,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert seen["url"] == "http://ocr.local/ocr"
    assert str(seen["content_type"]).startswith("multipart/form-data; boundary=")
    assert b'name="file"' in seen["body"]
    assert b'filename="screen.png"' in seen["body"]
    assert results == [{"text": "坐标 42", "score": 0.93, "box": [1, 2, 30, 40]}]


def test_asr_audio_returns_duration_and_segments(tmp_path):
    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"wav-bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://asr.local/asr"
        assert b'name="file"' in request.content
        return httpx.Response(
            200,
            json={
                "filename": "voice.wav",
                "duration": 3.5,
                "segments": [
                    {"start": 0.1, "end": 1.25, "speaker": "说话人1", "text": "目标出现"}
                ],
            },
        )

    result = asr_audio(
        "http://asr.local",
        audio_path,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert result == {
        "duration": 3.5,
        "segments": [{"start": 0.1, "end": 1.25, "speaker": "说话人1", "text": "目标出现"}],
    }


@pytest.mark.parametrize(
    ("response_status", "expected"),
    [(500, "HTTP 500"), (404, "HTTP 404")],
)
def test_ocr_image_status_error_raises_redacted_runtime_error(
    tmp_path,
    response_status,
    expected,
):
    image_path = tmp_path / "secret-name.png"
    image_path.write_bytes(b"png")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(response_status, json={"error": str(image_path)})

    with pytest.raises(RuntimeError) as exc_info:
        ocr_image(
            "http://ocr.local",
            image_path,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    message = str(exc_info.value)
    assert expected in message
    assert str(image_path) not in message
    assert "secret-name.png" not in message


def test_asr_audio_timeout_raises_redacted_runtime_error(tmp_path):
    audio_path = tmp_path / "private.wav"
    audio_path.write_bytes(b"wav")

    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException(f"timed out reading {audio_path}")

    with pytest.raises(RuntimeError) as exc_info:
        asr_audio(
            "http://asr.local",
            audio_path,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    message = str(exc_info.value)
    assert "ASR" in message
    assert "超时" in message
    assert str(audio_path) not in message
    assert "private.wav" not in message


def test_ocr_image_connect_error_raises_redacted_runtime_error(tmp_path):
    image_path = tmp_path / "private.png"
    image_path.write_bytes(b"png")

    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"connection refused for {image_path}")

    with pytest.raises(RuntimeError) as exc_info:
        ocr_image(
            "http://ocr.local",
            image_path,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    message = str(exc_info.value)
    assert "OCR" in message
    assert "连接失败" in message
    assert str(image_path) not in message
    assert "private.png" not in message


def test_check_media_health_probes_health_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://ocr.local/health"
        return httpx.Response(200, json={"status": "ok", "warmed": True})

    health = check_media_health(
        "http://ocr.local",
        service_name="OCR",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert health == {"status": "healthy", "warmed": True, "message": "OCR HTTP service ok"}


def test_check_media_health_returns_unavailable_for_bad_response():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=json.dumps({"detail": "cold"}).encode("utf-8"))

    health = check_media_health(
        "http://asr.local",
        service_name="ASR",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert health["status"] == "unavailable"
    assert "HTTP 503" in health["message"]
