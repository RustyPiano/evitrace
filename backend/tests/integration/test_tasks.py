import json

from app.config import settings
from app.database import SessionLocal
from app.models import AnalysisResult, AuditLog, Evidence, Task, TaskFile, TaskRun, User

from tests.conftest import login_headers


def _user_id(username: str) -> str:
    with SessionLocal() as db:
        return db.query(User).filter(User.username == username).one().id


def _insert_task(name: str, owner_id: str) -> str:
    with SessionLocal() as db:
        task = Task(name=name, objective="Objective", owner_id=owner_id, status="draft")
        db.add(task)
        db.commit()
        db.refresh(task)
        return task.id


def _create_task(client, headers) -> str:
    response = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"name": "Case", "objective": "Understand event"},
    )
    assert response.status_code == 201
    return response.json()["data"]["id"]


def _mark_awaiting_review_with_citation_check(task_id: str, citation_check: dict) -> None:
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        task.status = "awaiting_review"
        run = TaskRun(task_id=task_id, status="succeeded")
        db.add(run)
        db.flush()
        db.add(
            AnalysisResult(
                task_id=task_id,
                run_id=run.id,
                entities_json="[]",
                events_json="[]",
                timeline_json="[]",
                conflicts_json="[]",
                citation_check_json=json.dumps(citation_check),
            )
        )
        db.commit()


def _upload_text_file(client, headers, task_id: str) -> str:
    response = client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[("files", ("note.txt", b"secret", "text/plain"))],
    )
    assert response.status_code == 201
    return response.json()["data"][0]["id"]


def test_analyst_only_lists_own_tasks_and_admin_lists_all(client, create_user):
    create_user("alice")
    create_user("bob")
    alice_task = _insert_task("Alice task", _user_id("alice"))
    bob_task = _insert_task("Bob task", _user_id("bob"))

    alice_headers = login_headers(client, "alice", "password")
    admin_headers = login_headers(client, "admin", "admin-password")

    alice_response = client.get("/api/v1/tasks", headers=alice_headers)
    admin_response = client.get("/api/v1/tasks", headers=admin_headers)

    assert alice_response.status_code == 200
    assert {task["id"] for task in alice_response.json()["data"]} == {alice_task}
    assert admin_response.status_code == 200
    assert {task["id"] for task in admin_response.json()["data"]} == {alice_task, bob_task}


def test_analyst_accessing_another_users_task_returns_consistent_404(client, create_user):
    create_user("alice")
    create_user("bob")
    bob_task = _insert_task("Bob task", _user_id("bob"))
    alice_headers = login_headers(client, "alice", "password")

    response = client.get(f"/api/v1/tasks/{bob_task}", headers=alice_headers)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "TASK_NOT_FOUND"


def test_create_task_validates_fields(client, create_user):
    create_user("alice")
    headers = login_headers(client, "alice", "password")

    response = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"name": "", "objective": "Objective"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_ERROR"


def test_create_task_uses_current_user_and_draft_status(client, create_user):
    create_user("alice")
    headers = login_headers(client, "alice", "password")

    response = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"name": "Case", "objective": "Understand event", "description": "Notes"},
    )

    assert response.status_code == 201
    body = response.json()["data"]
    assert body["name"] == "Case"
    assert body["owner_id"] == _user_id("alice")
    assert body["status"] == "draft"


def test_completing_task_requires_awaiting_review(client, create_user):
    create_user("alice")
    headers = login_headers(client, "alice", "password")
    task_id = _create_task(client, headers)

    response = client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=headers,
        json={"status": "completed"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "INVALID_STATUS_TRANSITION"


def test_completing_task_from_awaiting_review_succeeds(client, create_user):
    create_user("alice")
    headers = login_headers(client, "alice", "password")
    task_id = _create_task(client, headers)
    _mark_awaiting_review_with_citation_check(
        task_id,
        {"invalid_citations": [], "citation_coverage": 0.9},
    )

    response = client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=headers,
        json={"status": "completed"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "completed"


def test_completing_task_rejects_low_citation_coverage_for_analyst(client, create_user):
    create_user("alice")
    headers = login_headers(client, "alice", "password")
    task_id = _create_task(client, headers)
    _mark_awaiting_review_with_citation_check(
        task_id,
        {"invalid_citations": [], "citation_coverage": 0.5},
    )

    response = client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=headers,
        json={"status": "completed"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CITATION_COVERAGE_TOO_LOW"


def test_completing_task_allows_admin_force_for_low_citation_coverage(client, create_user):
    task_id = _create_task(client, login_headers(client, "admin", "admin-password"))
    _mark_awaiting_review_with_citation_check(
        task_id,
        {"invalid_citations": [], "citation_coverage": 0.5},
    )

    response = client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=login_headers(client, "admin", "admin-password"),
        json={"status": "completed", "force": True},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "completed"


def test_completing_task_rejects_invalid_citations_even_for_admin_force(client, create_user):
    task_id = _create_task(client, login_headers(client, "admin", "admin-password"))
    _mark_awaiting_review_with_citation_check(
        task_id,
        {"invalid_citations": ["E-9999"], "citation_coverage": 1.0},
    )

    response = client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=login_headers(client, "admin", "admin-password"),
        json={"status": "completed", "force": True},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "INVALID_CITATIONS_PRESENT"


def test_delete_task_cascades_business_records_keeps_audit_logs_and_removes_directory(
    client, create_user
):
    create_user("alice")
    headers = login_headers(client, "alice", "password")
    task_id = _create_task(client, headers)
    file_id = _upload_text_file(client, headers, task_id)
    task_dir = settings.data_root_path / "tasks" / task_id
    with SessionLocal() as db:
        run = TaskRun(task_id=task_id, status="succeeded")
        db.add(run)
        db.flush()
        db.add(
            Evidence(
                display_id="E-0001",
                task_id=task_id,
                file_id=file_id,
                modality="text",
                evidence_type="paragraph",
                content="evidence",
                locator_json="{}",
                skill_id="document_parse",
            )
        )
        db.add(
            AnalysisResult(
                task_id=task_id,
                run_id=run.id,
                entities_json="[]",
                events_json="[]",
                timeline_json="[]",
                conflicts_json="[]",
                citation_check_json="{}",
            )
        )
        db.commit()

    response = client.delete(f"/api/v1/tasks/{task_id}", headers=headers)

    assert response.status_code == 200
    assert not task_dir.exists()
    with SessionLocal() as db:
        assert db.get(Task, task_id) is None
        assert db.query(TaskFile).filter(TaskFile.task_id == task_id).count() == 0
        assert db.query(Evidence).filter(Evidence.task_id == task_id).count() == 0
        assert db.query(TaskRun).filter(TaskRun.task_id == task_id).count() == 0
        assert db.query(AnalysisResult).filter(AnalysisResult.task_id == task_id).count() == 0
        actions = [
            row.action
            for row in db.query(AuditLog)
            .filter(AuditLog.resource_type == "task", AuditLog.resource_id == task_id)
            .order_by(AuditLog.created_at.asc())
        ]
    assert "task_created" in actions
    assert "file_uploaded" in actions
    assert "task_deleted" in actions


def test_delete_parsing_task_returns_task_already_running(client, create_user):
    create_user("alice")
    headers = login_headers(client, "alice", "password")
    task_id = _create_task(client, headers)
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        task.status = "parsing"
        db.commit()

    response = client.delete(f"/api/v1/tasks/{task_id}", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TASK_ALREADY_RUNNING"
