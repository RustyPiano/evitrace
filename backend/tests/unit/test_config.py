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
