import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="evitrace-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_ROOT / 'test.db'}"
os.environ["DATA_ROOT"] = str(_TEST_ROOT / "data")
os.environ["SECRET_KEY"] = "test-secret-key-with-at-least-32-bytes"
os.environ["FIRST_ADMIN_USERNAME"] = "admin"
os.environ["FIRST_ADMIN_PASSWORD"] = "admin-password"

# Hermetic test config: the suite must be deterministic regardless of the
# developer's local .env. Environment variables take precedence over the .env
# file in pydantic-settings, so pin the demo/mock defaults here. Without this, a
# real-mode .env (OCR_BASE_URL/ASR_BASE_URL/VLM_*) makes health and mock-media
# tests probe live local services and fail. Tests that need real mode override
# `settings` per-test via monkeypatch.
os.environ["MOCK_AI"] = "true"
for _hermetic_key in (
    "MOCK_LLM",
    "MOCK_MEDIA",
    "MOCK_VISION",
    "OCR_BASE_URL",
    "ASR_BASE_URL",
    "OCR_MODEL_DIR",
    "ASR_MODEL_DIR",
    "VLM_BASE_URL",
    "VLM_API_KEY",
    "VLM_MODEL",
):
    os.environ[_hermetic_key] = ""
os.environ["LOCAL_LLM_BASE_URL"] = "http://localhost:11434/v1"
os.environ["LOCAL_LLM_API_KEY"] = "local"
os.environ["LOCAL_LLM_MODEL"] = "qwen-local"

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import User
from app.services.auth_service import hash_password, seed_default_admin
from app.skills.registry import sync_skill_configs


@pytest.fixture(autouse=True)
def reset_database() -> None:
    shutil.rmtree(settings.data_root_path, ignore_errors=True)
    settings.data_root_path.mkdir(parents=True, exist_ok=True)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        seed_default_admin(db)
        sync_skill_configs(db)

    yield

    Base.metadata.drop_all(bind=engine)
    shutil.rmtree(settings.data_root_path, ignore_errors=True)


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def create_user() -> Callable[..., User]:
    def _create_user(
        username: str,
        password: str = "password",
        role: str = "analyst",
        is_active: bool = True,
    ) -> User:
        with SessionLocal() as db:
            user = User(
                username=username,
                password_hash=hash_password(password),
                role=role,
                is_active=is_active,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            user_id = user.id

        with SessionLocal() as db:
            return db.get(User, user_id)

    return _create_user


def login_headers(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
