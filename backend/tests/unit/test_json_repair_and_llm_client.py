import httpx
import pytest
from pydantic import BaseModel

from app.schemas import AppError
from app.services.llm_client import LocalLLMClient, _compute_delay
from app.utils.json_repair import loads_repaired_json


class SamplePayload(BaseModel):
    value: str


def _llm_response(status_code: int, content: str = '{"value":"ok"}', **kwargs) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        },
        **kwargs,
    )


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
    sleeps: list[float] = []

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
        sleep_fn=sleeps.append,
    )

    with pytest.raises(AppError) as exc_info:
        client.generate_json("system", "user", SamplePayload)

    assert exc_info.value.code == "LOCAL_MODEL_UNAVAILABLE"
    assert exc_info.value.http_status == 503
    assert len(calls) == 6
    assert len(sleeps) == 5


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


def test_llm_client_defaults_to_effective_mock_llm(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.settings.mock_ai", False)
    monkeypatch.setattr("app.services.llm_client.settings.mock_llm", None)

    assert LocalLLMClient().mock_ai is False

    monkeypatch.setattr("app.services.llm_client.settings.mock_llm", True)

    assert LocalLLMClient().mock_ai is True


def test_generate_json_retries_429_with_retry_after(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.settings.llm_rate_limit_max_retries", 5)
    monkeypatch.setattr("app.services.llm_client.settings.llm_backoff_max_sec", 30.0)
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) <= 2:
            return _llm_response(429, headers={"Retry-After": "2"})
        return _llm_response(200)

    client = LocalLLMClient(
        mock_ai=False,
        base_url="http://local-llm/v1",
        api_key="test-key",
        model="test-model",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep_fn=sleeps.append,
    )

    result = client.generate_json("system", "user", SamplePayload)

    assert result == SamplePayload(value="ok")
    assert calls == [1, 1, 1]
    assert sleeps == pytest.approx([2.0, 2.0])


def test_generate_json_raises_429_after_rate_limit_retries_exhausted(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.settings.llm_rate_limit_max_retries", 3)
    monkeypatch.setattr("app.services.llm_client.settings.llm_backoff_base_sec", 1.0)
    monkeypatch.setattr("app.services.llm_client.settings.llm_backoff_max_sec", 30.0)
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        return _llm_response(429)

    client = LocalLLMClient(
        mock_ai=False,
        base_url="http://local-llm/v1",
        api_key="test-key",
        model="test-model",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep_fn=sleeps.append,
    )

    with pytest.raises(AppError) as exc_info:
        client.generate_json("system", "user", SamplePayload)

    assert exc_info.value.code == "LLM_RATE_LIMITED"
    assert len(sleeps) == 3
    assert 0.5 <= sleeps[0] <= 1.0
    assert 1.0 <= sleeps[1] <= 2.0
    assert 2.0 <= sleeps[2] <= 4.0


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (402, "LLM_INSUFFICIENT_BALANCE"),
        (400, "LLM_REQUEST_INVALID"),
        (401, "LLM_REQUEST_INVALID"),
    ],
)
def test_generate_json_does_not_retry_fatal_http_errors(status_code, expected_code):
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _llm_response(status_code)

    client = LocalLLMClient(
        mock_ai=False,
        base_url="http://local-llm/v1",
        api_key="test-key",
        model="test-model",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep_fn=sleeps.append,
    )

    with pytest.raises(AppError) as exc_info:
        client.generate_json("system", "user", SamplePayload)

    assert exc_info.value.code == expected_code
    assert len(calls) == 1
    assert sleeps == []


@pytest.mark.parametrize("status_code", [500, 503])
def test_generate_json_retries_5xx_transient_errors(status_code, monkeypatch):
    monkeypatch.setattr("app.services.llm_client.settings.llm_rate_limit_max_retries", 1)
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return _llm_response(status_code, headers={"Retry-After": "1"})
        return _llm_response(200)

    client = LocalLLMClient(
        mock_ai=False,
        base_url="http://local-llm/v1",
        api_key="test-key",
        model="test-model",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep_fn=sleeps.append,
    )

    result = client.generate_json("system", "user", SamplePayload)

    assert result == SamplePayload(value="ok")
    assert len(calls) == 2
    assert sleeps == pytest.approx([1.0])


def test_generate_text_retries_transient_errors(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.settings.llm_rate_limit_max_retries", 1)
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return _llm_response(503, content="unused", headers={"Retry-After": "1"})
        return _llm_response(200, content=" ok ")

    client = LocalLLMClient(
        mock_ai=False,
        base_url="http://local-llm/v1",
        api_key="test-key",
        model="test-model",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep_fn=sleeps.append,
    )

    assert client.generate_text("system", "user") == "ok"
    assert len(calls) == 2
    assert sleeps == pytest.approx([1.0])


def test_generate_json_parse_errors_retry_without_sleep():
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _llm_response(200, content="not json")

    client = LocalLLMClient(
        mock_ai=False,
        base_url="http://local-llm/v1",
        api_key="test-key",
        model="test-model",
        max_retries=2,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep_fn=sleeps.append,
    )

    with pytest.raises(AppError) as exc_info:
        client.generate_json("system", "user", SamplePayload)

    assert exc_info.value.code == "INVALID_MODEL_OUTPUT"
    assert len(calls) == 3
    assert sleeps == []


def test_compute_delay_uses_retry_after_and_clamps_to_max():
    assert _compute_delay(2.0, attempt=0, base=1.0, max_sec=30.0) == 2.0
    assert _compute_delay(120.0, attempt=0, base=1.0, max_sec=30.0) == 30.0


def test_compute_delay_uses_exponential_backoff_with_jitter_range():
    delay = _compute_delay(None, attempt=2, base=1.0, max_sec=30.0, jitter=lambda: 0.25)

    assert delay == 2.5


def test_compute_delay_clamps_backoff_to_max():
    delay = _compute_delay(None, attempt=10, base=10.0, max_sec=30.0, jitter=lambda: 1.0)

    assert delay == 30.0


def test_mock_generate_json_does_not_call_http_or_sleep():
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("mock path should not call HTTP")

    client = LocalLLMClient(
        mock_ai=True,
        mock_json=lambda _system, _user, _schema: {"value": "mocked"},
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep_fn=sleeps.append,
    )

    assert client.generate_json("system", "user", SamplePayload) == SamplePayload(value="mocked")
    assert sleeps == []
