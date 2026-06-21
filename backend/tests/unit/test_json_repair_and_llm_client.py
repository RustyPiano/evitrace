import httpx
import pytest
from pydantic import BaseModel

from app.schemas import AppError
from app.services.llm_client import LocalLLMClient
from app.utils.json_repair import loads_repaired_json


class SamplePayload(BaseModel):
    value: str


def test_loads_repaired_json_strips_code_fence_and_trailing_commas():
    payload = loads_repaired_json('```json\n{"value": "ok",}\n```')

    assert payload == {"value": "ok"}


def test_mock_generate_json_uses_deterministic_callback():
    client = LocalLLMClient(
        mock_ai=True,
        mock_json=lambda _system, _user, _schema: {"value": "mocked"},
    )

    first = client.generate_json("system", "user", SamplePayload)
    second = client.generate_json("system", "user", SamplePayload)

    assert first == SamplePayload(value="mocked")
    assert second == SamplePayload(value="mocked")


def test_generate_json_retries_non_json_model_output():
    calls: list[int] = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        content = "not json" if len(calls) == 1 else '{"value":"ok"}'
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )

    client = LocalLLMClient(
        mock_ai=False,
        base_url="http://local-llm/v1",
        api_key="test-key",
        model="test-model",
        max_retries=2,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.generate_json("system", "user", SamplePayload)

    assert result == SamplePayload(value="ok")
    assert len(calls) == 2


def test_generate_json_raises_invalid_model_output_after_retries_exhausted():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "still not json"}}]})

    client = LocalLLMClient(
        mock_ai=False,
        base_url="http://local-llm/v1",
        api_key="test-key",
        model="test-model",
        max_retries=1,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(AppError) as exc_info:
        client.generate_json("system", "user", SamplePayload)

    assert exc_info.value.code == "INVALID_MODEL_OUTPUT"
    assert exc_info.value.http_status == 500


def test_generate_json_raises_model_unavailable_when_transport_fails():
    calls: list[int] = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("connection refused")

    client = LocalLLMClient(
        mock_ai=False,
        base_url="http://local-llm/v1",
        api_key="test-key",
        model="test-model",
        max_retries=1,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(AppError) as exc_info:
        client.generate_json("system", "user", SamplePayload)

    assert exc_info.value.code == "LOCAL_MODEL_UNAVAILABLE"
    assert exc_info.value.http_status == 503
    assert len(calls) == 2


def test_generate_json_retries_response_json_parse_errors():
    calls: list[int] = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(200, content=b"not-json")
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"value":"ok"}'}}]})

    client = LocalLLMClient(
        mock_ai=False,
        base_url="http://local-llm/v1",
        api_key="test-key",
        model="test-model",
        max_retries=2,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.generate_json("system", "user", SamplePayload)

    assert result == SamplePayload(value="ok")
    assert len(calls) == 2


def test_llm_max_retries_is_capped_at_two():
    client = LocalLLMClient(mock_ai=True, max_retries=99)

    assert client.max_retries == 2
