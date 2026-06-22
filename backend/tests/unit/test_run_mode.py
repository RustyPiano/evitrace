import json
import re

from app.config import settings
from app.utils.run_mode import run_mode_metadata


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
    assert metadata["mode_label"] == "演示Fixture"
    assert metadata["llm"] == {"real": False, "model": None}
    assert metadata["vision"] == {"real": False, "model": None}
    assert metadata["ocr"] == {"real": False, "source": "fixture"}
    assert metadata["asr"] == {"real": False, "source": "fixture"}
    assert {"id": "report_generate", "name": "报告生成与引用验证", "version": "1.0.0"} in metadata["skills"]
    _assert_no_secrets_or_urls(metadata)


def test_run_mode_metadata_all_real_is_real(monkeypatch):
    monkeypatch.setattr(settings, "mock_llm", False)
    monkeypatch.setattr(settings, "mock_media", False)
    monkeypatch.setattr(settings, "mock_vision", False)
    monkeypatch.setattr(settings, "local_llm_model", "deepseek-v4-flash")
    monkeypatch.setattr(settings, "vlm_model", "Qwen/VL")
    monkeypatch.setattr(settings, "vlm_api_key", "sk-vlm-secret")
    monkeypatch.setattr(settings, "vlm_base_url", "http://vlm.local/v1")
    monkeypatch.setattr(settings, "ocr_base_url", "http://ocr.local")
    monkeypatch.setattr(settings, "asr_base_url", None)

    metadata = run_mode_metadata()

    assert metadata["mode"] == "real"
    assert metadata["mode_label"] == "本地真实"
    assert metadata["llm"] == {"real": True, "model": "deepseek-v4-flash"}
    assert metadata["vision"] == {"real": True, "model": "Qwen/VL"}
    assert metadata["ocr"] == {"real": True, "source": "http"}
    assert metadata["asr"] == {"real": True, "source": "lib"}
    _assert_no_secrets_or_urls(metadata)


def test_run_mode_metadata_only_llm_real_is_hybrid(monkeypatch):
    monkeypatch.setattr(settings, "mock_llm", False)
    monkeypatch.setattr(settings, "mock_media", True)
    monkeypatch.setattr(settings, "mock_vision", True)
    monkeypatch.setattr(settings, "local_llm_model", "deepseek-v4-flash")

    metadata = run_mode_metadata()

    assert metadata["mode"] == "hybrid"
    assert metadata["mode_label"] == "混合模式"
    assert metadata["mock_llm"] is False
    assert metadata["mock_media"] is True
    assert metadata["mock_vision"] is True
    assert metadata["llm"] == {"real": True, "model": "deepseek-v4-flash"}
    assert metadata["ocr"] == {"real": False, "source": "fixture"}
    assert metadata["asr"] == {"real": False, "source": "fixture"}
    _assert_no_secrets_or_urls(metadata)
