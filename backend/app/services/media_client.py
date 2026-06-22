from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.utils.health_details import redact_health_detail


def ocr_image(
    base_url: str,
    image_path: Path | str,
    *,
    http_client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    data = _post_file(base_url, "ocr", image_path, service_name="OCR", http_client=http_client)
    results = data.get("results") or []
    if not isinstance(results, list):
        raise RuntimeError("OCR 服务响应结构无效")
    return [item for item in results if isinstance(item, dict)]


def asr_audio(
    base_url: str,
    audio_path: Path | str,
    *,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    data = _post_file(base_url, "asr", audio_path, service_name="ASR", http_client=http_client)
    segments = data.get("segments") or []
    if not isinstance(segments, list):
        raise RuntimeError("ASR 服务响应结构无效")
    return {"duration": data.get("duration"), "segments": [item for item in segments if isinstance(item, dict)]}


def check_media_health(
    base_url: str,
    *,
    service_name: str,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    close_client = False
    client = http_client
    if client is None:
        client = httpx.Client(timeout=settings.media_timeout_sec)
        close_client = True

    try:
        response = client.get(_url(base_url, "health"), timeout=settings.media_timeout_sec)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as exc:
        return _unavailable(f"{service_name} HTTP service returned HTTP {exc.response.status_code}")
    except httpx.TimeoutException:
        return _unavailable(f"{service_name} HTTP service timed out")
    except httpx.ConnectError:
        return _unavailable(f"{service_name} HTTP service connection failed")
    except httpx.HTTPError:
        return _unavailable(f"{service_name} HTTP service request failed")
    except ValueError:
        return _unavailable(f"{service_name} HTTP service returned invalid JSON")
    finally:
        if close_client:
            client.close()

    if not isinstance(data, dict):
        return _unavailable(f"{service_name} HTTP service returned invalid health payload")
    if data.get("status") == "ok":
        return {
            "status": "healthy",
            "warmed": bool(data.get("warmed")),
            "message": f"{service_name} HTTP service ok",
        }
    return _unavailable(f"{service_name} HTTP service status {data.get('status') or 'unknown'}")


def _post_file(
    base_url: str,
    endpoint: str,
    file_path: Path | str,
    *,
    service_name: str,
    http_client: httpx.Client | None,
) -> dict[str, Any]:
    path = Path(file_path)
    close_client = False
    client = http_client
    if client is None:
        client = httpx.Client(timeout=settings.media_timeout_sec)
        close_client = True

    try:
        with path.open("rb") as file_handle:
            response = client.post(
                _url(base_url, endpoint),
                files={"file": (path.name, file_handle)},
                timeout=settings.media_timeout_sec,
            )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            redact_health_detail(f"{service_name} 服务返回 HTTP {exc.response.status_code}")
        ) from exc
    except httpx.TimeoutException as exc:
        raise RuntimeError(redact_health_detail(f"{service_name} 服务请求超时")) from exc
    except httpx.ConnectError as exc:
        raise RuntimeError(redact_health_detail(f"{service_name} 服务连接失败")) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(redact_health_detail(f"{service_name} 服务请求失败")) from exc
    finally:
        if close_client:
            client.close()

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(redact_health_detail(f"{service_name} 服务响应不是有效 JSON")) from exc
    if not isinstance(data, dict):
        raise RuntimeError(redact_health_detail(f"{service_name} 服务响应结构无效"))
    return data


def _url(base_url: str, endpoint: str) -> str:
    return f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"


def _unavailable(message: str) -> dict[str, str]:
    return {"status": "unavailable", "message": redact_health_detail(message)}
