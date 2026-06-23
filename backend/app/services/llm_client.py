import logging
import random
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import perf_counter
import time
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
SleepCallback = Callable[[float], None]

RETRYABLE_TRANSIENT = {"LLM_RATE_LIMITED", "LOCAL_MODEL_UNAVAILABLE"}
FATAL = {"LLM_REQUEST_INVALID", "LLM_INSUFFICIENT_BALANCE"}


def _compute_delay(
    retry_after: float | None,
    attempt: int,
    base: float,
    max_sec: float,
    jitter: Callable[[], float] = random.random,
) -> float:
    if retry_after is not None:
        return min(max(retry_after, 0.0), max_sec)
    delay = base * (2**attempt) * (0.5 + jitter() * 0.5)
    return min(max(delay, 0.0), max_sec)


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return max(float(stripped), 0.0)
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max((retry_at - datetime.now(timezone.utc)).total_seconds(), 0.0)


def _app_error(
    code: str,
    message: str,
    http_status: int,
    retry_after: float | None = None,
) -> AppError:
    error = AppError(code, message, http_status)
    setattr(error, "retry_after", retry_after)
    return error


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
        sleep_fn: SleepCallback | None = None,
    ) -> None:
        self.mock_ai = settings.effective_mock_llm if mock_ai is None else mock_ai
        self.base_url = (base_url or settings.local_llm_base_url).rstrip("/")
        self.api_key = api_key or settings.local_llm_api_key
        self.model = model or settings.local_llm_model
        self.timeout_sec = timeout_sec or settings.llm_timeout_sec
        configured_retries = settings.llm_max_retries if max_retries is None else max_retries
        self.max_retries = max(0, min(configured_retries, 2))
        self.http_client = http_client
        self.mock_json = mock_json
        self.mock_text = mock_text
        self._sleep = sleep_fn or time.sleep

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

        transient_retries = 0
        parse_retries = 0
        last_parse_error: Exception | None = None
        while True:
            try:
                content = self._chat_completion(system_prompt, user_prompt)
            except AppError as exc:
                if exc.code in RETRYABLE_TRANSIENT:
                    if transient_retries >= settings.llm_rate_limit_max_retries:
                        raise
                    delay = _compute_delay(
                        getattr(exc, "retry_after", None),
                        transient_retries,
                        settings.llm_backoff_base_sec,
                        settings.llm_backoff_max_sec,
                    )
                    logger.warning(
                        "LLM retry transient code=%s attempt=%s delay=%.2fs",
                        exc.code,
                        transient_retries,
                        delay,
                    )
                    self._sleep(delay)
                    transient_retries += 1
                    continue
                if exc.code == "INVALID_MODEL_OUTPUT":
                    if parse_retries >= self.max_retries:
                        raise
                    last_parse_error = exc
                    logger.warning(
                        "Local LLM response structure invalid attempt=%s",
                        parse_retries + 1,
                    )
                    parse_retries += 1
                    continue
                if exc.code in FATAL:
                    logger.warning("LLM fatal code=%s", exc.code)
                raise
            try:
                parsed = loads_repaired_json(content)
                validated = schema.model_validate(parsed)
            except (ValueError, ValidationError) as exc:
                if parse_retries >= self.max_retries:
                    raise AppError(
                        "INVALID_MODEL_OUTPUT",
                        "模型输出无法校验",
                        status.HTTP_500_INTERNAL_SERVER_ERROR,
                    ) from exc
                last_parse_error = exc
                logger.warning(
                    "Local LLM returned invalid JSON attempt=%s schema=%s error=%s",
                    parse_retries + 1,
                    schema.__name__,
                    type(exc).__name__,
                )
                parse_retries += 1
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

        transient_retries = 0
        parse_retries = 0
        last_error: Exception | None = None
        while True:
            try:
                content = self._chat_completion(system_prompt, user_prompt)
            except AppError as exc:
                last_error = exc
                if exc.code in RETRYABLE_TRANSIENT:
                    if transient_retries >= settings.llm_rate_limit_max_retries:
                        raise
                    delay = _compute_delay(
                        getattr(exc, "retry_after", None),
                        transient_retries,
                        settings.llm_backoff_base_sec,
                        settings.llm_backoff_max_sec,
                    )
                    logger.warning(
                        "LLM retry transient code=%s attempt=%s delay=%.2fs",
                        exc.code,
                        transient_retries,
                        delay,
                    )
                    self._sleep(delay)
                    transient_retries += 1
                    continue
                if exc.code in FATAL:
                    logger.warning("LLM fatal code=%s", exc.code)
                    raise
                if exc.code != "INVALID_MODEL_OUTPUT":
                    raise
                if parse_retries >= self.max_retries:
                    raise
                parse_retries += 1
                continue
            if content.strip():
                return content.strip()
            if parse_retries >= self.max_retries:
                break
            logger.warning("Local LLM returned empty text attempt=%s", parse_retries + 1)
            parse_retries += 1

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
            status_code = exc.response.status_code
            retry_after = _parse_retry_after(exc.response.headers.get("Retry-After"))
            if status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                raise _app_error(
                    "LLM_RATE_LIMITED",
                    "上游模型限流，请稍后重试",
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    retry_after,
                ) from exc
            if status_code in {
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                status.HTTP_502_BAD_GATEWAY,
                status.HTTP_503_SERVICE_UNAVAILABLE,
                status.HTTP_504_GATEWAY_TIMEOUT,
            }:
                raise _app_error(
                    "LOCAL_MODEL_UNAVAILABLE",
                    f"本地模型返回 HTTP {status_code}",
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    retry_after,
                ) from exc
            if status_code == status.HTTP_402_PAYMENT_REQUIRED:
                raise _app_error(
                    "LLM_INSUFFICIENT_BALANCE",
                    "上游余额不足/欠费，请检查模型服务账户",
                    status.HTTP_402_PAYMENT_REQUIRED,
                ) from exc
            if status_code in {
                status.HTTP_400_BAD_REQUEST,
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
                status.HTTP_404_NOT_FOUND,
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            }:
                raise _app_error(
                    "LLM_REQUEST_INVALID",
                    f"模型请求无效，HTTP {status_code}",
                    status_code,
                ) from exc
            raise _app_error(
                "LOCAL_MODEL_UNAVAILABLE",
                f"本地模型返回 HTTP {status_code}",
                status.HTTP_503_SERVICE_UNAVAILABLE,
                retry_after,
            ) from exc
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
            raise _app_error(
                "LOCAL_MODEL_UNAVAILABLE",
                "本地模型不可用",
                status.HTTP_503_SERVICE_UNAVAILABLE,
                None,
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
