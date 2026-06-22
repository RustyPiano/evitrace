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
        OCR_MODEL_DIR="/models/ocr",
        ASR_MODEL_DIR="/models/asr",
        ASR_MODEL_SIZE="small",
        FFMPEG_TIMEOUT_SEC=30,
        VLM_BASE_URL="http://vlm.local/v1",
        VLM_API_KEY="vlm-key",
        VLM_MODEL="qwen-vl",
    )

    assert settings.ocr_model_dir == "/models/ocr"
    assert settings.asr_model_dir == "/models/asr"
    assert settings.asr_model_size == "small"
    assert settings.ffmpeg_timeout_sec == 30
    assert settings.vlm_base_url == "http://vlm.local/v1"
    assert settings.vlm_api_key == "vlm-key"
    assert settings.vlm_model == "qwen-vl"


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
