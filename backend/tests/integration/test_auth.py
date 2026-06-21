from app.database import SessionLocal
from app.models import AuditLog

from tests.conftest import login_headers


def test_login_with_correct_password_returns_token(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin-password"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["username"] == "admin"
    assert body["user"]["role"] == "admin"
    assert "password" not in body["user"]

    with SessionLocal() as db:
        actions = [row.action for row in db.query(AuditLog).all()]
    assert "login_success" in actions


def test_login_with_wrong_password_returns_401(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "INVALID_CREDENTIALS"

    with SessionLocal() as db:
        actions = [row.action for row in db.query(AuditLog).all()]
    assert "login_failed" in actions


def test_inactive_user_login_returns_403(client, create_user):
    create_user("disabled", is_active=False)

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "disabled", "password": "password"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "INACTIVE_USER"


def test_missing_token_returns_401(client):
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "INVALID_CREDENTIALS"


def test_non_admin_is_rejected_by_admin_dependency(client, create_user):
    create_user("analyst")
    headers = login_headers(client, "analyst", "password")

    response = client.get("/api/v1/admin/health", headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "FORBIDDEN"
