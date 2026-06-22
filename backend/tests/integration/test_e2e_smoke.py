import re
from pathlib import Path
from urllib.parse import unquote

from app.constants import RUN_STATUS_SUCCEEDED, TASK_STATUS_AWAITING_REVIEW
from app.database import SessionLocal
from app.models import Task, User
from app.services.auth_service import hash_password


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
REPORT_HEADINGS = [
    "## 一、任务概述",
    "## 二、资料概况",
    "## 三、事件时间线",
    "## 四、主要冲突",
    "## 五、综合分析结论",
    "## 六、未确认事项",
]


def _set_admin_demo_password() -> None:
    with SessionLocal() as db:
        admin = db.query(User).filter(User.username == "admin").one()
        admin.password_hash = hash_password("admin123456")
        db.commit()


def _login_demo_admin(client) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123456"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_backend_e2e_smoke_happy_path_in_mock_demo_mode(client):
    _set_admin_demo_password()
    headers = _login_demo_admin(client)

    create_response = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"name": "E2E Smoke", "objective": "完成端到端冒烟验证"},
    )
    assert create_response.status_code == 201
    task_id = create_response.json()["data"]["id"]

    sample_path = FIXTURES_DIR / "sample.txt"
    upload_response = client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[
            (
                "files",
                (sample_path.name, sample_path.read_bytes(), "text/plain"),
            )
        ],
    )
    assert upload_response.status_code == 201
    assert upload_response.json()["data"][0]["status"] == "uploaded"

    run_response = client.post(f"/api/v1/tasks/{task_id}/runs", headers=headers)
    assert run_response.status_code == 202
    run_id = run_response.json()["data"]["run_id"]

    latest_response = client.get(f"/api/v1/tasks/{task_id}/runs/latest", headers=headers)
    assert latest_response.status_code == 200
    latest_run = latest_response.json()["data"]
    assert latest_run["run_id"] == run_id
    assert latest_run["status"] == RUN_STATUS_SUCCEEDED
    assert latest_run["current_step"] == "awaiting_review"
    assert latest_run["progress"] == 100

    task_response = client.get(f"/api/v1/tasks/{task_id}", headers=headers)
    assert task_response.status_code == 200
    assert task_response.json()["data"]["status"] == TASK_STATUS_AWAITING_REVIEW
    with SessionLocal() as db:
        assert db.get(Task, task_id).status == TASK_STATUS_AWAITING_REVIEW

    results_response = client.get(f"/api/v1/tasks/{task_id}/results", headers=headers)
    assert results_response.status_code == 200
    results = results_response.json()["data"]
    assert results["run_id"] == run_id
    assert len(results["events"]) >= 1
    assert len(results["timeline"]) >= 1
    assert len(results["conflicts"]) >= 1
    assert results["report_markdown"]
    for heading in REPORT_HEADINGS:
        assert heading in results["report_markdown"]
    assert "> 运行模式：演示Fixture" in results["report_markdown"]
    assert results["citation_check"]["invalid_citation_count"] == 0
    assert results["citation_check"]["invalid_citations"] == []

    evidence_response = client.get(f"/api/v1/tasks/{task_id}/evidence", headers=headers)
    assert evidence_response.status_code == 200
    evidence_items = evidence_response.json()["data"]["items"]
    assert len(evidence_items) >= 1
    assert re.fullmatch(r"E-\d{4}", evidence_items[0]["display_id"])

    index_response = client.get(f"/api/v1/tasks/{task_id}/evidence/index", headers=headers)
    assert index_response.status_code == 200
    evidence_index = index_response.json()["data"]
    assert len(evidence_index) == len(evidence_items)
    assert evidence_index[0]["display_id"] == evidence_items[0]["display_id"]

    download_response = client.get(f"/api/v1/tasks/{task_id}/report/download", headers=headers)
    assert download_response.status_code == 200
    assert download_response.headers["content-type"].startswith("text/markdown")
    disposition = unquote(download_response.headers["content-disposition"])
    assert "attachment" in disposition
    assert "E2E_Smoke_分析报告_" in disposition
    assert disposition.endswith(".md")

    mode_response = client.get("/api/v1/system/mode", headers=headers)
    assert mode_response.status_code == 200
    mode = mode_response.json()["data"]
    assert mode["mode"] == "mock"
    assert mode["mode_label"] == "演示Fixture"
