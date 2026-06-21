from app.database import SessionLocal
from app.models import Task, User

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
