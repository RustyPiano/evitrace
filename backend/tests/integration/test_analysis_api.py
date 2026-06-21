from urllib.parse import unquote

from app.constants import (
    RUN_STATUS_FAILED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCEEDED,
    TASK_STATUS_AWAITING_REVIEW,
    TASK_STATUS_FAILED,
    TASK_STATUS_PARSING,
)
from app.database import SessionLocal
from app.models import AnalysisResult, Evidence, SkillConfig, Task, TaskFile, TaskRun
from app.services import orchestrator

from tests.conftest import login_headers


def _create_task(client, headers, name: str = "M3 Case") -> str:
    response = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"name": name, "objective": "分析事件、冲突并生成报告"},
    )
    assert response.status_code == 201
    return response.json()["data"]["id"]


def _upload_text(client, headers, task_id: str) -> str:
    response = client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[
            (
                "files",
                (
                    "note.txt",
                    "6月1日14:00，车队在地点A发现3辆车。\n\n6月1日16:30，车队在地点B发现5辆车。".encode(),
                    "text/plain",
                ),
            )
        ],
    )
    assert response.status_code == 201
    return response.json()["data"][0]["id"]


def test_analysis_mock_flow_results_patch_download_and_rerun(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    _upload_text(client, headers, task_id)

    start_response = client.post(f"/api/v1/tasks/{task_id}/runs", headers=headers)

    assert start_response.status_code == 202
    first_run_id = start_response.json()["data"]["run_id"]
    latest = client.get(f"/api/v1/tasks/{task_id}/runs/latest", headers=headers).json()["data"]
    assert latest["run_id"] == first_run_id
    assert latest["status"] == RUN_STATUS_SUCCEEDED
    assert latest["progress"] == 100

    results_response = client.get(f"/api/v1/tasks/{task_id}/results", headers=headers)
    assert results_response.status_code == 200
    results = results_response.json()["data"]
    assert len(results["events"]) >= 2
    assert len(results["timeline"]) >= 2
    assert len(results["conflicts"]) >= 1
    assert results["report_markdown"].startswith("# M3 Case")
    assert results["citation_check"]["invalid_citations"] == []
    assert results["citation_check"]["citation_coverage"] >= 0.9

    conflict_id = results["conflicts"][0]["conflict_id"]
    patch_response = client.patch(
        f"/api/v1/tasks/{task_id}/conflicts/{conflict_id}",
        headers=headers,
        json={"status": "confirmed"},
    )
    assert patch_response.status_code == 200
    patched = client.get(f"/api/v1/tasks/{task_id}/results", headers=headers).json()["data"]
    assert patched["conflicts"][0]["status"] == "confirmed"

    regenerate_response = client.post(f"/api/v1/tasks/{task_id}/report/regenerate", headers=headers)
    assert regenerate_response.status_code == 200
    assert regenerate_response.json()["data"]["citation_check"]["invalid_citations"] == []

    download_response = client.get(f"/api/v1/tasks/{task_id}/report/download", headers=headers)
    assert download_response.status_code == 200
    assert download_response.text.startswith("# M3 Case")
    assert "分析报告" in unquote(download_response.headers["content-disposition"])

    with SessionLocal() as db:
        old_evidence_ids = {row.id for row in db.query(Evidence).filter(Evidence.task_id == task_id)}
        first_result_id = db.query(AnalysisResult).filter(AnalysisResult.task_id == task_id).one().id

    rerun_response = client.post(f"/api/v1/tasks/{task_id}/runs", headers=headers)
    assert rerun_response.status_code == 202
    second_run_id = rerun_response.json()["data"]["run_id"]
    assert second_run_id != first_run_id

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        runs = db.query(TaskRun).filter(TaskRun.task_id == task_id).order_by(TaskRun.started_at.asc()).all()
        new_evidence_ids = {row.id for row in db.query(Evidence).filter(Evidence.task_id == task_id)}
        result = db.query(AnalysisResult).filter(AnalysisResult.task_id == task_id).one()
        assert task.status == TASK_STATUS_AWAITING_REVIEW
        assert [run.id for run in runs] == [first_run_id, second_run_id]
        assert old_evidence_ids.isdisjoint(new_evidence_ids)
        assert result.id != first_result_id
        assert result.run_id == second_run_id


def test_start_run_rejects_task_without_files(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)

    response = client.post(f"/api/v1/tasks/{task_id}/runs", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TASK_NOT_READY"


def test_start_run_rejects_when_required_skill_disabled(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    _upload_text(client, headers, task_id)
    with SessionLocal() as db:
        config = db.get(SkillConfig, "intelligence_extract")
        config.enabled = False
        db.commit()

    response = client.post(f"/api/v1/tasks/{task_id}/runs", headers=headers)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "REQUIRED_SKILL_UNAVAILABLE"


def test_start_run_rejects_when_any_task_is_running(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    running_task_id = _create_task(client, headers, "Running")
    waiting_task_id = _create_task(client, headers, "Waiting")
    _upload_text(client, headers, waiting_task_id)
    with SessionLocal() as db:
        db.get(Task, running_task_id).status = TASK_STATUS_PARSING
        db.commit()

    response = client.post(f"/api/v1/tasks/{waiting_task_id}/runs", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TASK_ALREADY_RUNNING"


def test_analysis_results_and_download_enforce_owner_access(client, create_user):
    create_user("owner")
    create_user("other")
    owner_headers = login_headers(client, "owner", "password")
    other_headers = login_headers(client, "other", "password")
    task_id = _create_task(client, owner_headers)
    _upload_text(client, owner_headers, task_id)
    client.post(f"/api/v1/tasks/{task_id}/runs", headers=owner_headers)

    results_response = client.get(f"/api/v1/tasks/{task_id}/results", headers=other_headers)
    download_response = client.get(f"/api/v1/tasks/{task_id}/report/download", headers=other_headers)

    assert results_response.status_code == 404
    assert download_response.status_code == 404


def test_orchestrator_progress_updates_are_monotonic(client, create_user, monkeypatch):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    _upload_text(client, headers, task_id)
    seen: list[int] = []
    original_update_state = orchestrator._update_state

    def spy_update_state(db, task, run, *, task_status, run_status=None, progress=None, current_step=None):
        if progress is not None:
            seen.append(progress)
        return original_update_state(
            db,
            task,
            run,
            task_status=task_status,
            run_status=run_status,
            progress=progress,
            current_step=current_step,
        )

    monkeypatch.setattr(orchestrator, "_update_state", spy_update_state)

    orchestrator.run_task(task_id)

    assert seen == sorted(seen)
    assert seen[0] == 0
    assert seen[-1] == 100


def test_recover_interrupted_runs_marks_running_records_failed():
    with SessionLocal() as db:
        task = Task(name="Interrupted", objective="Recover", owner_id="admin", status="parsing")
        db.add(task)
        db.flush()
        db.add(
            TaskFile(
                task_id=task.id,
                original_name="note.txt",
                stored_name="note.txt",
                extension="txt",
                mime_type="text/plain",
                size_bytes=4,
                modality="text",
            )
        )
        run = TaskRun(task_id=task.id, status=RUN_STATUS_RUNNING, progress=55, current_step="extracting")
        db.add(run)
        db.commit()
        task_id = task.id
        run_id = run.id

    orchestrator.recover_interrupted_runs()

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        run = db.get(TaskRun, run_id)
        assert task.status == TASK_STATUS_FAILED
        assert task.last_error == "服务重启导致运行中断，请重新执行"
        assert run.status == RUN_STATUS_FAILED
        assert run.error_message == "服务重启导致运行中断，请重新执行"
