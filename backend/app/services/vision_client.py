from __future__ import annotations

import base64
import logging
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx

from app.config import settings
from app.utils.health_details import redact_health_detail

logger = logging.getLogger(__name__)


class VisionClient:
    def __init__(
        self,
        *,
        mock_media: bool | None = None,
        mock_vision: bool | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_sec: int | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        configured_base_url = settings.vlm_base_url if base_url is None else base_url
        configured_model = settings.vlm_model if model is None else model
        if mock_vision is None:
            mock_vision = mock_media if mock_media is not None else settings.effective_mock_vision
        self.mock_vision = mock_vision
        self.mock_media = mock_vision
        self.base_url = configured_base_url.rstrip("/") if configured_base_url else None
        self.api_key = settings.vlm_api_key if api_key is None else api_key
        self.model = configured_model.strip() if configured_model else None
        self.timeout_sec = timeout_sec or settings.llm_timeout_sec
        self.http_client = http_client

    def describe_image(self, image_path: Path | str, prompt: str) -> str:
        path = Path(image_path)
        if self.mock_vision:
            return f"MOCK 画面描述：{path.name} 显示一处训练场景，包含可供复核的目标、车辆或人员活动线索。"

        self._require_real_config()
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": self._data_url(path)}},
                    ],
                }
            ],
            "temperature": 0,
        }
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        close_client = False
        client = self.http_client
        if client is None:
            client = httpx.Client(timeout=self.timeout_sec)
            close_client = True

        started = perf_counter()
        try:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout_sec,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"VLM 返回 HTTP {exc.response.status_code}") from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError("VLM 请求超时") from exc
        except httpx.ConnectError as exc:
            raise RuntimeError("VLM 连接失败") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"VLM 请求失败: {redact_health_detail(exc)}") from exc
        except ValueError as exc:
            raise RuntimeError("VLM 响应不是有效 JSON") from exc
        finally:
            if close_client:
                client.close()

        content = self._extract_content(data)
        duration_ms = int((perf_counter() - started) * 1000)
        logger.info("VLM call completed model=%s duration_ms=%s", self.model, duration_ms)
        return content

    def _require_real_config(self) -> None:
        if not self.base_url or not self.model or not self.api_key:
            raise RuntimeError("VLM_BASE_URL/VLM_MODEL/VLM_API_KEY 未配置，真实视觉理解需要支持图像输入的 VLM 端点")

    @staticmethod
    def _data_url(path: Path) -> str:
        data = path.read_bytes()
        ext = path.suffix.lower().lstrip(".") or "png"
        media_ext = "jpeg" if ext == "jpg" else ext
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:image/{media_ext};base64,{encoded}"

    @staticmethod
    def _extract_content(data: Any) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("VLM 响应结构无效") from exc

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
            text = "\n".join(part for part in parts if part.strip()).strip()
        else:
            text = str(content or "").strip()
        if not text:
            raise RuntimeError("VLM 输出为空")
        return text


def require_vision_config() -> None:
    VisionClient(mock_vision=False)._require_real_config()
