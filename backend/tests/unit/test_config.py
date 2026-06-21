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
    )

    assert settings.ocr_model_dir == "/models/ocr"
    assert settings.asr_model_dir == "/models/asr"
    assert settings.asr_model_size == "small"
    assert settings.ffmpeg_timeout_sec == 30
