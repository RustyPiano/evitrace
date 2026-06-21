import json

from app.database import SessionLocal
from app.models import AuditLog

from tests.conftest import login_headers


def test_admin_health_requires_admin_and_returns_sanitized_components(client, create_user):
    create_user("analyst")
    analyst_headers = login_headers(client, "analyst", "password")
    admin_headers = login_headers(client, "admin", "admin-password")

    forbidden = client.get("/api/v1/admin/health", headers=analyst_headers)
    response = client.get("/api/v1/admin/health", headers=admin_headers)

    assert forbidden.status_code == 403
    assert response.status_code == 200
    components = response.json()["data"]["components"]
    names = {item["component"] for item in components}
    assert names == {"database", "disk", "llm", "ffmpeg", "ocr", "asr"}
    assert {item["status"] for item in components} <= {"healthy", "unavailable", "skipped"}
    assert all("/" not in item["detail"] for item in components)
    assert all("\\" not in item["detail"] for item in components)


def test_admin_audit_logs_requires_admin_and_paginates(client, create_user):
    create_user("analyst")
    analyst_headers = login_headers(client, "analyst", "password")
    admin_headers = login_headers(client, "admin", "admin-password")
    client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={"username": "new-analyst", "password": "password", "role": "analyst"},
    )

    forbidden = client.get("/api/v1/admin/audit-logs", headers=analyst_headers)
    response = client.get("/api/v1/admin/audit-logs?page=1&page_size=2", headers=admin_headers)

    assert forbidden.status_code == 403
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert data["total"] >= 1
    assert len(data["items"]) <= 2
    first = data["items"][0]
    assert {"id", "user_id", "username", "action", "resource_type", "resource_id", "detail", "created_at"} <= set(first)
    assert isinstance(first["detail"], dict)
    assert "password" not in json.dumps(first["detail"], ensure_ascii=False)


def test_admin_audit_logs_include_analysis_start_and_report_download(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"name": "Audit Case", "objective": "验证审计"},
    ).json()["data"]
    upload = client.post(
        f"/api/v1/tasks/{task['id']}/files",
        headers=headers,
        files=[("files", ("note.txt", "6月1日14:00，车队在地点A发现3辆车。".encode(), "text/plain"))],
    )
    assert upload.status_code == 201

    run_response = client.post(f"/api/v1/tasks/{task['id']}/runs", headers=headers)
    download_response = client.get(f"/api/v1/tasks/{task['id']}/report/download", headers=headers)

    assert run_response.status_code == 202
    assert download_response.status_code == 200
    latest = client.get(f"/api/v1/tasks/{task['id']}/runs/latest", headers=headers).json()["data"]
    assert "plan_json" in latest
    assert "steps" in latest["plan_json"]
    with SessionLocal() as db:
        audits = (
            db.query(AuditLog)
            .filter(AuditLog.resource_type == "task", AuditLog.resource_id == task["id"])
            .order_by(AuditLog.created_at.asc())
            .all()
        )
    actions = [audit.action for audit in audits]
    assert "analysis_started" in actions
    assert "report_downloaded" in actions
    for audit in audits:
        assert "note.txt" not in audit.detail_json
