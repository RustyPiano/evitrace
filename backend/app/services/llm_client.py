import logging
from collections.abc import Callable
from time import perf_counter
from typing import Any

import httpx
from fastapi import status
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.schemas import AppError
from app.utils.json_repair import loads_repaired_json

logger = logging.getLogger(__name__)

MockJsonCallback = Callable[[str, str, type[BaseModel]], BaseModel | dict[str, Any] | str]
MockTextCallback = Callable[[str, str], str]


class LocalLLMClient:
    def __init__(
        self,
        *,
        mock_ai: bool | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_sec: int | None = None,
        max_retries: int | None = None,
        http_client: httpx.Client | None = None,
        mock_json: MockJsonCallback | None = None,
        mock_text: MockTextCallback | None = None,
    ) -> None:
        self.mock_ai = settings.mock_ai if mock_ai is None else mock_ai
        self.base_url = (base_url or settings.local_llm_base_url).rstrip("/")
        self.api_key = api_key or settings.local_llm_api_key
        self.model = model or settings.local_llm_model
        self.timeout_sec = timeout_sec or settings.llm_timeout_sec
        configured_retries = settings.llm_max_retries if max_retries is None else max_retries
        self.max_retries = max(0, min(configured_retries, 2))
        self.http_client = http_client
        self.mock_json = mock_json
        self.mock_text = mock_text

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: type[BaseModel],
    ) -> BaseModel:
        if self.mock_ai:
            if self.mock_json is None:
                return schema.model_validate({})
            raw = self.mock_json(system_prompt, user_prompt, schema)
            if isinstance(raw, schema):
                return raw
            if isinstance(raw, str):
                raw = loads_repaired_json(raw)
            return schema.model_validate(raw)

        last_parse_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                content = self._chat_completion(system_prompt, user_prompt)
            except AppError as exc:
                if exc.code == "LOCAL_MODEL_UNAVAILABLE":
                    logger.warning("Local LLM unavailable attempt=%s", attempt + 1)
                    if attempt >= self.max_retries:
                        raise
                    continue
                if exc.code == "INVALID_MODEL_OUTPUT":
                    last_parse_error = exc
                    logger.warning("Local LLM response structure invalid attempt=%s", attempt + 1)
                    continue
                raise
            try:
                parsed = loads_repaired_json(content)
                validated = schema.model_validate(parsed)
            except (ValueError, ValidationError) as exc:
                last_parse_error = exc
                logger.warning(
                    "Local LLM returned invalid JSON attempt=%s schema=%s error=%s",
                    attempt + 1,
                    schema.__name__,
                    type(exc).__name__,
                )
                continue
            return validated

        raise AppError(
            "INVALID_MODEL_OUTPUT",
            "模型输出无法校验",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from last_parse_error

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        if self.mock_ai:
            if self.mock_text is not None:
                return self.mock_text(system_prompt, user_prompt)
            return "AI 辅助生成，需人工复核。"

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                content = self._chat_completion(system_prompt, user_prompt)
            except AppError as exc:
                last_error = exc
                if exc.code == "LOCAL_MODEL_UNAVAILABLE":
                    logger.warning("Local LLM unavailable attempt=%s", attempt + 1)
                    if attempt >= self.max_retries:
                        raise
                    continue
                if exc.code != "INVALID_MODEL_OUTPUT":
                    raise
                continue
            if content.strip():
                return content.strip()
            logger.warning("Local LLM returned empty text attempt=%s", attempt + 1)

        raise AppError(
            "INVALID_MODEL_OUTPUT",
            "模型输出为空",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from last_error

    def health_check(self) -> dict[str, Any]:
        if self.mock_ai:
            return {"status": "healthy", "mode": "mock", "skipped": True}
        try:
            self.generate_text("health check", "ping")
        except AppError as exc:
            return {"status": "error", "code": exc.code, "message": exc.message}
        return {"status": "healthy", "mode": "real", "skipped": False}

    def _chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        started = perf_counter()
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        }
        close_client = False
        client = self.http_client
        if client is None:
            client = httpx.Client(timeout=self.timeout_sec)
            close_client = True

        try:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=self.timeout_sec,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise AppError(
                "LOCAL_MODEL_UNAVAILABLE",
                f"本地模型返回 HTTP {exc.response.status_code}",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
            raise AppError(
                "LOCAL_MODEL_UNAVAILABLE",
                "本地模型不可用",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc
        finally:
            if close_client:
                client.close()

        try:
            data = response.json()
        except ValueError as exc:
            raise AppError(
                "INVALID_MODEL_OUTPUT",
                "模型响应不是有效 JSON",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc
        duration_ms = int((perf_counter() - started) * 1000)
        usage = data.get("usage") if isinstance(data, dict) else None
        if isinstance(usage, dict):
            logger.info(
                "Local LLM call completed model=%s duration_ms=%s prompt_tokens=%s completion_tokens=%s",
                self.model,
                duration_ms,
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
            )
        else:
            logger.info("Local LLM call completed model=%s duration_ms=%s", self.model, duration_ms)

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AppError(
                "INVALID_MODEL_OUTPUT",
                "模型响应结构无效",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc
        return str(content)


def ping_local_llm() -> dict[str, Any]:
    return LocalLLMClient().health_check()
