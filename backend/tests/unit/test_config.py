import pytest
from pydantic import ValidationError

from app.config import Settings


def test_production_rejects_default_secret_key():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(
            ENV="production",
            SECRET_KEY="change-me",
            FIRST_ADMIN_PASSWORD="not-default-admin-password",
        )


def test_production_rejects_short_secret_key():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(
            ENV="production",
            SECRET_KEY="x" * 31,
            FIRST_ADMIN_PASSWORD="not-default-admin-password",
        )


def test_production_rejects_default_admin_password():
    with pytest.raises(ValidationError, match="FIRST_ADMIN_PASSWORD"):
        Settings(
            ENV="production",
            SECRET_KEY="x" * 32,
            FIRST_ADMIN_PASSWORD="admin123456",
        )


def test_development_warns_for_default_credentials(capsys):
    Settings(
        ENV="development",
        SECRET_KEY="change-me",
        FIRST_ADMIN_PASSWORD="admin123456",
    )

    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "SECRET_KEY" in captured.err
    assert "FIRST_ADMIN_PASSWORD" in captured.err


def test_local_model_and_ffmpeg_timeout_settings_are_configurable():
    settings = Settings(
        SECRET_KEY="x" * 32,
        FIRST_ADMIN_PASSWORD="not-default-admin-password",
        OCR_BASE_URL="http://127.0.0.1:8000",
        ASR_BASE_URL="http://127.0.0.1:8001",
        OCR_MODEL_DIR="/models/ocr",
        ASR_MODEL_DIR="/models/asr",
        ASR_MODEL_SIZE="small",
        MEDIA_TIMEOUT_SEC=240,
        FFMPEG_TIMEOUT_SEC=30,
        VLM_BASE_URL="http://vlm.local/v1",
        VLM_API_KEY="vlm-key",
        VLM_MODEL="qwen-vl",
    )

    assert settings.ocr_base_url == "http://127.0.0.1:8000"
    assert settings.asr_base_url == "http://127.0.0.1:8001"
    assert settings.ocr_model_dir == "/models/ocr"
    assert settings.asr_model_dir == "/models/asr"
    assert settings.asr_model_size == "small"
    assert settings.media_timeout_sec == 240
    assert settings.ffmpeg_timeout_sec == 30
    assert settings.vlm_base_url == "http://vlm.local/v1"
    assert settings.vlm_api_key == "vlm-key"
    assert settings.vlm_model == "qwen-vl"


def test_extract_concurrency_is_clamped_to_supported_range():
    too_low = Settings(
        SECRET_KEY="x" * 32,
        FIRST_ADMIN_PASSWORD="not-default-admin-password",
        EXTRACT_CONCURRENCY=0,
    )
    too_high = Settings(
        SECRET_KEY="x" * 32,
        FIRST_ADMIN_PASSWORD="not-default-admin-password",
        EXTRACT_CONCURRENCY=99,
    )

    assert too_low.extract_concurrency == 1
    assert too_high.extract_concurrency == 16


def test_extract_cost_controls_are_clamped_to_supported_ranges():
    too_low = Settings(
        SECRET_KEY="x" * 32,
        FIRST_ADMIN_PASSWORD="not-default-admin-password",
        EXTRACT_BATCH_MAX_ITEMS=0,
        EXTRACT_BATCH_MAX_CHARS=999,
        EXTRACT_MIN_EVIDENCE_CHARS=-1,
        EXTRACT_MAX_FILES_CONFIRM=-1,
    )
    too_high = Settings(
        SECRET_KEY="x" * 32,
        FIRST_ADMIN_PASSWORD="not-default-admin-password",
        EXTRACT_BATCH_MAX_ITEMS=999,
        EXTRACT_BATCH_MAX_CHARS=999999,
        EXTRACT_MIN_EVIDENCE_CHARS=9999,
        EXTRACT_MAX_FILES_CONFIRM=999999,
    )

    assert too_low.extract_batch_max_items == 1
    assert too_low.extract_batch_max_chars == 1000
    assert too_low.extract_min_evidence_chars == 0
    assert too_low.extract_max_files_confirm == 0
    assert too_high.extract_batch_max_items == 500
    assert too_high.extract_batch_max_chars == 120000
    assert too_high.extract_min_evidence_chars == 2000
    assert too_high.extract_max_files_confirm == 100000


def test_empty_media_service_urls_become_none():
    settings = Settings(
        SECRET_KEY="x" * 32,
        FIRST_ADMIN_PASSWORD="not-default-admin-password",
        OCR_BASE_URL="",
        ASR_BASE_URL="  ",
    )

    assert settings.ocr_base_url is None
    assert settings.asr_base_url is None


def test_mock_llm_and_media_default_to_mock_ai():
    all_mock = Settings(
        SECRET_KEY="x" * 32,
        FIRST_ADMIN_PASSWORD="not-default-admin-password",
        MOCK_AI=True,
    )
    all_real = Settings(
        SECRET_KEY="x" * 32,
        FIRST_ADMIN_PASSWORD="not-default-admin-password",
        MOCK_AI=False,
    )

    assert all_mock.effective_mock_llm is True
    assert all_mock.effective_mock_media is True
    assert all_real.effective_mock_llm is False
    assert all_real.effective_mock_media is False


def test_mock_llm_and_media_can_be_split_for_cloud_llm_with_mock_media():
    settings = Settings(
        SECRET_KEY="x" * 32,
        FIRST_ADMIN_PASSWORD="not-default-admin-password",
        MOCK_AI=False,
        MOCK_MEDIA=True,
    )

    assert settings.effective_mock_llm is False
    assert settings.effective_mock_media is True


def test_effective_mock_vision_follows_vlm_config_independent_of_media_mock():
    settings = Settings(
        SECRET_KEY="x" * 32,
        FIRST_ADMIN_PASSWORD="not-default-admin-password",
        MOCK_AI=False,
        MOCK_MEDIA=True,
        VLM_BASE_URL="https://vlm.example/v1",
        VLM_API_KEY="vlm-key",
        VLM_MODEL="qwen-vl",
    )

    assert settings.effective_mock_media is True
    assert settings.vlm_configured is True
    assert settings.effective_mock_vision is False


def test_effective_mock_vision_defaults_to_mock_when_vlm_is_not_configured():
    settings = Settings(
        SECRET_KEY="x" * 32,
        FIRST_ADMIN_PASSWORD="not-default-admin-password",
        MOCK_AI=False,
        MOCK_MEDIA=False,
    )

    assert settings.effective_mock_media is False
    assert settings.vlm_configured is False
    assert settings.effective_mock_vision is True


def test_mock_vision_explicit_override_wins_and_empty_string_means_auto():
    forced_mock = Settings(
        SECRET_KEY="x" * 32,
        FIRST_ADMIN_PASSWORD="not-default-admin-password",
        MOCK_VISION=True,
        VLM_BASE_URL="https://vlm.example/v1",
        VLM_API_KEY="vlm-key",
        VLM_MODEL="qwen-vl",
    )
    forced_real = Settings(
        SECRET_KEY="x" * 32,
        FIRST_ADMIN_PASSWORD="not-default-admin-password",
        MOCK_VISION=False,
    )
    auto = Settings(
        SECRET_KEY="x" * 32,
        FIRST_ADMIN_PASSWORD="not-default-admin-password",
        MOCK_VISION="",
        VLM_BASE_URL="https://vlm.example/v1",
        VLM_API_KEY="vlm-key",
        VLM_MODEL="qwen-vl",
    )

    assert forced_mock.effective_mock_vision is True
    assert forced_real.effective_mock_vision is False
    assert auto.mock_vision is None
    assert auto.effective_mock_vision is False
