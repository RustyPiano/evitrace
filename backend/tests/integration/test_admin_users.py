import json

from app.database import SessionLocal
from app.models import AuditLog, User

from tests.conftest import login_headers


def _user_id(username: str) -> str:
    with SessionLocal() as db:
        return db.query(User).filter(User.username == username).one().id


def test_admin_can_create_analyst_and_analyst_can_login(client):
    admin_headers = login_headers(client, "admin", "admin-password")

    response = client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={
            "username": "analyst-api",
            "role": "analyst",
            "password": "analyst-password",
        },
    )

    assert response.status_code == 201
    body = response.json()["data"]
    assert body["username"] == "analyst-api"
    assert body["role"] == "analyst"
    assert body["is_active"] is True
    assert "password" not in body

    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "analyst-api", "password": "analyst-password"},
    )
    assert login_response.status_code == 200
    assert login_response.json()["user"]["role"] == "analyst"

    with SessionLocal() as db:
        audit = (
            db.query(AuditLog)
            .filter(AuditLog.action == "user_created")
            .order_by(AuditLog.created_at.desc())
            .first()
        )
    assert audit is not None
    assert json.loads(audit.detail_json) == {"username": "analyst-api", "role": "analyst"}


def test_non_admin_cannot_list_admin_users(client, create_user):
    create_user("analyst")
    headers = login_headers(client, "analyst", "password")

    response = client.get("/api/v1/admin/users", headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "FORBIDDEN"


def test_cannot_deactivate_last_active_admin(client):
    admin_headers = login_headers(client, "admin", "admin-password")
    admin_id = _user_id("admin")

    response = client.patch(
        f"/api/v1/admin/users/{admin_id}",
        headers=admin_headers,
        json={"is_active": False},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "LAST_ACTIVE_ADMIN"


def test_cannot_deactivate_self(client, create_user):
    create_user("backup-admin", role="admin")
    admin_headers = login_headers(client, "admin", "admin-password")
    admin_id = _user_id("admin")

    response = client.patch(
        f"/api/v1/admin/users/{admin_id}",
        headers=admin_headers,
        json={"is_active": False},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CANNOT_MODIFY_SELF"


def test_admin_can_update_role_and_reset_password_without_auditing_plaintext(client, create_user):
    create_user("promote-me", password="old-password")
    admin_headers = login_headers(client, "admin", "admin-password")
    user_id = _user_id("promote-me")

    response = client.patch(
        f"/api/v1/admin/users/{user_id}",
        headers=admin_headers,
        json={"role": "admin", "password": "new-password"},
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["role"] == "admin"

    old_login = client.post(
        "/api/v1/auth/login",
        json={"username": "promote-me", "password": "old-password"},
    )
    new_login = client.post(
        "/api/v1/auth/login",
        json={"username": "promote-me", "password": "new-password"},
    )
    assert old_login.status_code == 401
    assert new_login.status_code == 200

    with SessionLocal() as db:
        audit = (
            db.query(AuditLog)
            .filter(AuditLog.action == "user_updated")
            .order_by(AuditLog.created_at.desc())
            .first()
        )
    assert audit is not None
    detail = json.loads(audit.detail_json)
    assert detail["changed_fields"] == ["role", "password"]
    assert detail["password_reset"] is True
    assert "new-password" not in audit.detail_json
