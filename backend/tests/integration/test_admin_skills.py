from app.database import SessionLocal
from app.models import SkillConfig

from tests.conftest import login_headers


def test_admin_cannot_disable_required_skill(client):
    headers = login_headers(client, "admin", "admin-password")

    response = client.patch(
        "/api/v1/admin/skills/report_generate",
        headers=headers,
        json={"enabled": False},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "REQUIRED_SKILL_CANNOT_DISABLE"
    with SessionLocal() as db:
        assert db.get(SkillConfig, "report_generate").enabled is True


def test_admin_can_disable_non_required_skill(client):
    headers = login_headers(client, "admin", "admin-password")

    response = client.patch(
        "/api/v1/admin/skills/image_ocr",
        headers=headers,
        json={"enabled": False},
    )

    assert response.status_code == 200
    assert response.json()["data"]["enabled"] is False
    with SessionLocal() as db:
        assert db.get(SkillConfig, "image_ocr").enabled is False
