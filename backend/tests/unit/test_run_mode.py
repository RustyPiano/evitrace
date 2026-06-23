import json
import re

from app.config import settings
from app.utils.run_mode import _deployment_from_url, run_mode_metadata


def _serialized(metadata: dict) -> str:
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True)


def _assert_no_secrets_or_urls(metadata: dict) -> None:
    serialized = _serialized(metadata)
    assert "sk-" not in serialized
    assert "base_url" not in serialized
    assert "api_key" not in serialized
    assert re.search(r"https?://", serialized) is None


def test_run_mode_metadata_all_mock_is_mock(monkeypatch):
    monkeypatch.setattr(settings, "mock_llm", True)
    monkeypatch.setattr(settings, "mock_media", True)
    monkeypatch.setattr(settings, "mock_vision", True)
    monkeypatch.setattr(settings, "local_llm_model", "deepseek-v4-flash")
    monkeypatch.setattr(settings, "vlm_model", "Qwen/VL")
    monkeypatch.setattr(settings, "local_llm_api_key", "sk-secret")
    monkeypatch.setattr(settings, "local_llm_base_url", "http://llm.local/v1")
    monkeypatch.setattr(settings, "ocr_base_url", "http://ocr.local")
    monkeypatch.setattr(settings, "asr_base_url", "http://asr.local")

    metadata = run_mode_metadata()

    assert metadata["mode"] == "mock"
    assert metadata["execution_mode"] == "mock"
    assert metadata["mode_label"] == "演示Fixture"
    assert metadata["deployment_mode"] is None
    assert metadata["llm"] == {"real": False, "model": None, "deployment": None}
    assert metadata["vision"] == {"real": False, "model": None, "deployment": None}
    assert metadata["ocr"] == {"real": False, "source": "fixture", "deployment": None}
    assert metadata["asr"] == {"real": False, "source": "fixture", "deployment": None}
    assert {"id": "report_generate", "name": "报告生成与引用验证", "version": "1.0.0"} in metadata["skills"]
    _assert_no_secrets_or_urls(metadata)


def test_run_mode_metadata_all_real_is_real(monkeypatch):
    monkeypatch.setattr(settings, "mock_llm", False)
    monkeypatch.setattr(settings, "mock_media", False)
    monkeypatch.setattr(settings, "mock_vision", False)
    monkeypatch.setattr(settings, "local_llm_model", "deepseek-v4-flash")
    monkeypatch.setattr(settings, "local_llm_base_url", "https://api.deepseek.com/v1")
    monkeypatch.setattr(settings, "vlm_model", "Qwen/VL")
    monkeypatch.setattr(settings, "vlm_api_key", "sk-vlm-secret")
    monkeypatch.setattr(settings, "vlm_base_url", "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(settings, "ocr_base_url", "http://127.0.0.1:8000")
    monkeypatch.setattr(settings, "asr_base_url", None)

    metadata = run_mode_metadata()

    assert metadata["mode"] == "real"
    assert metadata["execution_mode"] == "real"
    assert metadata["mode_label"] == "全真实链路"
    assert metadata["deployment_mode"] == "mixed"
    assert metadata["llm"] == {
        "real": True,
        "model": "deepseek-v4-flash",
        "deployment": "remote",
    }
    assert metadata["vision"] == {"real": True, "model": "Qwen/VL", "deployment": "remote"}
    assert metadata["ocr"] == {"real": True, "source": "http", "deployment": "local"}
    assert metadata["asr"] == {"real": True, "source": "lib", "deployment": "local"}
    _assert_no_secrets_or_urls(metadata)


def test_run_mode_metadata_only_llm_real_is_hybrid(monkeypatch):
    monkeypatch.setattr(settings, "mock_llm", False)
    monkeypatch.setattr(settings, "mock_media", True)
    monkeypatch.setattr(settings, "mock_vision", True)
    monkeypatch.setattr(settings, "local_llm_model", "deepseek-v4-flash")
    monkeypatch.setattr(settings, "local_llm_base_url", "https://api.deepseek.com/v1")

    metadata = run_mode_metadata()

    assert metadata["mode"] == "hybrid"
    assert metadata["execution_mode"] == "hybrid"
    assert metadata["mode_label"] == "混合模式"
    assert metadata["deployment_mode"] == "remote"
    assert metadata["mock_llm"] is False
    assert metadata["mock_media"] is True
    assert metadata["mock_vision"] is True
    assert metadata["llm"] == {
        "real": True,
        "model": "deepseek-v4-flash",
        "deployment": "remote",
    }
    assert metadata["ocr"] == {"real": False, "source": "fixture", "deployment": None}
    assert metadata["asr"] == {"real": False, "source": "fixture", "deployment": None}
    _assert_no_secrets_or_urls(metadata)


def test_deployment_from_url_derives_local_remote_without_exposing_url():
    assert _deployment_from_url("https://api.deepseek.com/v1") == "remote"
    assert _deployment_from_url("http://127.0.0.1:8000") == "local"
    assert _deployment_from_url("http://host.docker.internal:8001") == "local"
    assert _deployment_from_url(None) is None
