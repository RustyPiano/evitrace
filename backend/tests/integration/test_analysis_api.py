from datetime import datetime, timezone
from urllib.parse import unquote

import pytest

from app.constants import (
    RUN_STATUS_FAILED,
    RUN_STATUS_QUEUED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCEEDED,
    TASK_STATUS_AWAITING_REVIEW,
    TASK_STATUS_EXTRACTING,
    TASK_STATUS_FAILED,
    TASK_STATUS_PARSING,
)
from app.database import SessionLocal
from app.models import AnalysisResult, AuditLog, Evidence, SkillConfig, Task, TaskFile, TaskRun
from app.schemas import AppError
from app.services import orchestrator
from app.skills.base import RunCancelled
from app.skills.base import SkillResult

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


def _upload_texts(client, headers, task_id: str, count: int) -> list[str]:
    response = client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[
            (
                "files",
                (
                    f"note-{index}.txt",
                    f"6月1日14:00，车队在地点{index}发现{index}辆车。".encode(),
                    "text/plain",
                ),
            )
            for index in range(1, count + 1)
        ],
    )
    assert response.status_code == 201
    return [item["id"] for item in response.json()["data"]]


def _admin_create_analyst(client, admin_headers, username: str) -> None:
    response = client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={"username": username, "password": "password", "role": "analyst"},
    )
    assert response.status_code == 201


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
    assert {conflict["type"] for conflict in results["conflicts"]} >= {"time", "location", "quantity"}
    assert results["report_markdown"].startswith("**AI 辅助生成，需人工复核。**")
    assert "# M3 Case" in results["report_markdown"]
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
    assert download_response.text.startswith("**AI 辅助生成，需人工复核。**")
    assert "# M3 Case" in download_response.text
    assert "分析报告" in unquote(download_response.headers["content-disposition"])

    with SessionLocal() as db:
        first_evidence = db.query(Evidence).filter(Evidence.task_id == task_id).order_by(Evidence.display_id).all()
        first_evidence_ids = {row.id for row in first_evidence}
        first_display_ids = [row.display_id for row in first_evidence]
        assert first_evidence
        assert {row.run_id for row in first_evidence} == {first_run_id}
        first_result = db.query(AnalysisResult).filter(AnalysisResult.task_id == task_id).one()
        first_result_id = first_result.id

    rerun_response = client.post(f"/api/v1/tasks/{task_id}/runs", headers=headers)
    assert rerun_response.status_code == 202
    second_run_id = rerun_response.json()["data"]["run_id"]
    assert second_run_id != first_run_id

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        runs = db.query(TaskRun).filter(TaskRun.task_id == task_id).order_by(TaskRun.started_at.asc()).all()
        all_evidence = db.query(Evidence).filter(Evidence.task_id == task_id).order_by(Evidence.display_id).all()
        second_evidence = [row for row in all_evidence if row.run_id == second_run_id]
        results = db.query(AnalysisResult).filter(AnalysisResult.task_id == task_id).order_by(AnalysisResult.created_at).all()
        assert task.status == TASK_STATUS_AWAITING_REVIEW
        assert [run.id for run in runs] == [first_run_id, second_run_id]
        assert first_evidence_ids.issubset({row.id for row in all_evidence})
        assert len(results) == 2
        assert [result.run_id for result in results] == [first_run_id, second_run_id]
        assert results[0].id == first_result_id
        assert first_display_ids[-1] < second_evidence[0].display_id
        assert {row.run_id for row in second_evidence} == {second_run_id}

    latest_results = client.get(f"/api/v1/tasks/{task_id}/results", headers=headers).json()["data"]
    historical_results = client.get(
        f"/api/v1/tasks/{task_id}/results?run_id={first_run_id}",
        headers=headers,
    ).json()["data"]
    assert latest_results["run_id"] == second_run_id
    assert historical_results["run_id"] == first_run_id

    latest_evidence = client.get(f"/api/v1/tasks/{task_id}/evidence", headers=headers).json()["data"]
    historical_evidence = client.get(
        f"/api/v1/tasks/{task_id}/evidence?run_id={first_run_id}",
        headers=headers,
    ).json()["data"]
    assert {item["id"] for item in latest_evidence["items"]} == {row.id for row in second_evidence}
    assert {item["id"] for item in historical_evidence["items"]} == first_evidence_ids

    runs_response = client.get(f"/api/v1/tasks/{task_id}/runs", headers=headers)
    assert runs_response.status_code == 200
    listed_runs = runs_response.json()["data"]
    assert [item["run_id"] for item in listed_runs] == [second_run_id, first_run_id]
    assert all(item["has_result"] for item in listed_runs)


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


def test_start_run_large_file_guard_requires_confirmation(client, create_user, monkeypatch):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    _upload_texts(client, headers, task_id, 2)
    monkeypatch.setattr(orchestrator.settings, "extract_max_files_confirm", 1, raising=False)

    with SessionLocal() as db:
        owner = db.query(Task).filter(Task.id == task_id).one().owner
        with pytest.raises(AppError) as exc_info:
            orchestrator.start_run(db, task_id, owner)

    assert exc_info.value.code == "RUN_TOO_LARGE"
    assert exc_info.value.http_status == 409

    with SessionLocal() as db:
        owner = db.query(Task).filter(Task.id == task_id).one().owner
        run = orchestrator.start_run(db, task_id, owner, confirm_large=True)
        assert run.status == RUN_STATUS_QUEUED


def test_start_run_large_file_guard_allows_disabled_or_below_threshold(client, create_user, monkeypatch):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    disabled_task_id = _create_task(client, headers, "Disabled guard")
    below_task_id = _create_task(client, headers, "Below guard")
    _upload_texts(client, headers, disabled_task_id, 2)
    _upload_texts(client, headers, below_task_id, 2)

    monkeypatch.setattr(orchestrator.settings, "extract_max_files_confirm", 0, raising=False)
    with SessionLocal() as db:
        owner = db.query(Task).filter(Task.id == disabled_task_id).one().owner
        run = orchestrator.start_run(db, disabled_task_id, owner)
        assert run.status == RUN_STATUS_QUEUED
        run.status = RUN_STATUS_FAILED
        db.get(Task, disabled_task_id).status = "ready"
        db.commit()

    monkeypatch.setattr(orchestrator.settings, "extract_max_files_confirm", 2, raising=False)
    with SessionLocal() as db:
        owner = db.query(Task).filter(Task.id == below_task_id).one().owner
        run = orchestrator.start_run(db, below_task_id, owner)
        assert run.status == RUN_STATUS_QUEUED


def test_start_analysis_run_large_file_guard_body_contract(client, create_user, monkeypatch):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    _upload_texts(client, headers, task_id, 2)
    monkeypatch.setattr(orchestrator.settings, "extract_max_files_confirm", 1, raising=False)

    rejected = client.post(f"/api/v1/tasks/{task_id}/runs", headers=headers)

    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "RUN_TOO_LARGE"

    accepted = client.post(
        f"/api/v1/tasks/{task_id}/runs",
        headers=headers,
        json={"confirm_large": True},
    )

    assert accepted.status_code == 202
    assert accepted.json()["data"]["status"] == "queued"


def test_cancel_run_marks_latest_running_run_and_records_audit(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        task.status = TASK_STATUS_EXTRACTING
        run = TaskRun(task_id=task_id, status=RUN_STATUS_RUNNING, progress=55, current_step="extracting")
        db.add(run)
        db.commit()
        run_id = run.id

    response = client.post(f"/api/v1/tasks/{task_id}/runs/cancel", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"] == {"run_id": run_id, "cancel_requested": True}
    with SessionLocal() as db:
        run = db.get(TaskRun, run_id)
        audit = db.query(AuditLog).filter(AuditLog.action == "analysis_cancel_requested").one()
        assert run.cancel_requested is True
        assert audit.resource_id == task_id


def test_cancel_run_returns_conflict_when_no_run_is_active(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)

    response = client.post(f"/api/v1/tasks/{task_id}/runs/cancel", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "NO_RUNNING_RUN"


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


def test_execute_run_passes_run_id_and_parse_progress_window(client, create_user, monkeypatch):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    _upload_text(client, headers, task_id)
    with SessionLocal() as db:
        owner = db.query(Task).filter(Task.id == task_id).one().owner
        run = orchestrator.start_run(db, task_id, owner)
        run_id = run.id

    call_args: dict[str, object] = {}

    def fake_parse(
        _task_id: str,
        run_id: str | None = None,
        progress_start: int = 0,
        progress_end: int = 100,
        **_kwargs,
    ):
        call_args.update(
            {
                "task_id": _task_id,
                "run_id": run_id,
                "progress_start": progress_start,
                "progress_end": progress_end,
            }
        )
        return orchestrator.parse_service.ParseSummary(task_id=_task_id, run_id=run_id)

    def stop_after_parse(_db, _task_id):
        raise RuntimeError("stop after parse")

    monkeypatch.setattr(orchestrator.parse_service, "parse_all_files", fake_parse)
    monkeypatch.setattr(orchestrator, "_list_evidence", stop_after_parse)

    orchestrator.execute_run(task_id, run_id)

    assert call_args == {
        "task_id": task_id,
        "run_id": run_id,
        "progress_start": 10,
        "progress_end": 45,
    }


def test_execute_run_cancelled_during_extraction_finishes_cancelled_without_later_skills(
    client,
    create_user,
    monkeypatch,
):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    _upload_text(client, headers, task_id)
    with SessionLocal() as db:
        owner = db.query(Task).filter(Task.id == task_id).one().owner
        run = orchestrator.start_run(db, task_id, owner)
        run_id = run.id

    def fake_parse(_task_id: str, run_id: str | None = None, **_kwargs):
        return orchestrator.parse_service.ParseSummary(task_id=_task_id, run_id=run_id)

    class CancelExtract:
        def run(self, _context, _payload, **_kwargs):
            raise RunCancelled()

    class UnexpectedSkill:
        def run(self, *_args, **_kwargs):
            raise AssertionError("later analysis skills must not run after cancellation")

    monkeypatch.setattr(orchestrator.parse_service, "parse_all_files", fake_parse)
    monkeypatch.setattr(
        orchestrator,
        "_list_evidence",
        lambda _db, _run_id: [
            {
                "display_id": "E-0001",
                "content": "6月1日14:00，车队在地点A发现3辆车。",
                "content_summary": "6月1日14:00，车队在地点A发现3辆车。",
                "file": {"original_name": "note.txt"},
                "locator": {"kind": "text"},
                "modality": "text",
                "evidence_type": "paragraph",
            }
        ],
    )
    monkeypatch.setattr(orchestrator, "IntelligenceExtractSkill", CancelExtract)
    monkeypatch.setattr(orchestrator, "ConflictDetectSkill", UnexpectedSkill)
    monkeypatch.setattr(orchestrator, "ReportGenerateSkill", UnexpectedSkill)

    orchestrator.execute_run(task_id, run_id)

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        run = db.get(TaskRun, run_id)
        assert task.status == TASK_STATUS_FAILED
        assert task.last_error == "分析已手动取消"
        assert run.status == RUN_STATUS_FAILED
        assert run.current_step == "cancelled"
        assert run.error_message == "分析已手动取消"
        assert run.resumable is True


def test_start_run_resets_historical_cancel_requested_flag(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    _upload_text(client, headers, task_id)
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        task.status = "ready"
        old_run = TaskRun(task_id=task_id, status=RUN_STATUS_QUEUED, cancel_requested=True)
        db.add(old_run)
        db.commit()
        owner = task.owner
        run = orchestrator.start_run(db, task_id, owner)
        run_id = run.id

    with SessionLocal() as db:
        assert db.get(TaskRun, run_id).cancel_requested is False


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
        assert run.current_step == "failed"
        assert run.resumable is True


def test_resume_run_endpoint_resets_run_and_records_audit(client, create_user, monkeypatch):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    _upload_text(client, headers, task_id)
    scheduled: list[tuple[str, str]] = []
    monkeypatch.setattr(orchestrator, "execute_run", lambda task_id, run_id: scheduled.append((task_id, run_id)))
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        task.status = TASK_STATUS_FAILED
        run = TaskRun(
            task_id=task_id,
            status=RUN_STATUS_FAILED,
            current_step="failed",
            progress=70,
            resumable=True,
            cancel_requested=True,
            error_message="partial",
            finished_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.commit()
        run_id = run.id

    response = client.post(f"/api/v1/tasks/{task_id}/runs/{run_id}/resume", headers=headers)

    assert response.status_code == 202
    assert response.json()["data"] == {"run_id": run_id, "status": RUN_STATUS_QUEUED}
    assert scheduled == [(task_id, run_id)]
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        run = db.get(TaskRun, run_id)
        audit = db.query(AuditLog).filter(AuditLog.action == "analysis_resumed").one()
        assert task.status == "queued"
        assert run.status == RUN_STATUS_QUEUED
        assert run.current_step == "queued"
        assert run.cancel_requested is False
        assert run.error_message is None
        assert run.finished_at is None
        assert run.resumable is True
        assert run.progress == 0
        assert run.total_batches == 0
        assert run.done_batches == 0
        assert run.failed_batches == 0
        assert run.estimated_input_tokens == 0
        assert audit.resource_id == task_id
        assert audit.detail_json


def test_resume_run_endpoint_rejects_non_resumable_run(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    with SessionLocal() as db:
        run = TaskRun(task_id=task_id, status=RUN_STATUS_FAILED, resumable=False)
        db.add(run)
        db.commit()
        run_id = run.id

    response = client.post(f"/api/v1/tasks/{task_id}/runs/{run_id}/resume", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RUN_NOT_RESUMABLE"


def test_resume_run_endpoint_rejects_when_any_task_is_running(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    running_task_id = _create_task(client, headers, "Running")
    with SessionLocal() as db:
        db.get(Task, running_task_id).status = TASK_STATUS_PARSING
        run = TaskRun(task_id=task_id, status=RUN_STATUS_FAILED, resumable=True)
        db.add(run)
        db.commit()
        run_id = run.id

    response = client.post(f"/api/v1/tasks/{task_id}/runs/{run_id}/resume", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TASK_ALREADY_RUNNING"


def test_execute_run_all_failed_extraction_marks_resumable_without_result(client, create_user, monkeypatch):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    file_id = _upload_text(client, headers, task_id)
    with SessionLocal() as db:
        owner = db.query(Task).filter(Task.id == task_id).one().owner
        run = orchestrator.start_run(db, task_id, owner)
        run_id = run.id

    def fake_parse(_task_id: str, run_id: str | None = None, **_kwargs):
        with SessionLocal() as db:
            db.add(
                Evidence(
                    display_id="E-0001",
                    task_id=_task_id,
                    run_id=run_id,
                    file_id=file_id,
                    modality="text",
                    evidence_type="paragraph",
                    content="6月1日14:00，车队在地点A发现3辆车。",
                    locator_json="{}",
                    skill_id="document_parse",
                )
            )
            db.commit()
        return orchestrator.parse_service.ParseSummary(task_id=_task_id, run_id=run_id)

    class AllFailedExtract:
        def run(self, _context, _payload, **_kwargs):
            return SkillResult(
                success=True,
                warnings=["部分抽取失败：0/1 批成功、1 批失败（可在工作台『继续分析』续跑补齐）"],
                data={"entities": [], "events": [], "timeline": []},
                metrics={"batch_total": 1, "batch_done": 0, "batch_failed": 1, "batch_aborted": True},
            )

    monkeypatch.setattr(orchestrator.parse_service, "parse_all_files", fake_parse)
    monkeypatch.setattr(orchestrator, "IntelligenceExtractSkill", AllFailedExtract)

    orchestrator.execute_run(task_id, run_id)

    with SessionLocal() as db:
        run = db.get(TaskRun, run_id)
        assert run.status == RUN_STATUS_FAILED
        assert run.resumable is True
        assert run.total_batches == 1
        assert run.done_batches == 0
        assert run.failed_batches == 1
        assert run.error_message == "全部抽取批次失败，可在工作台续跑"
        assert db.query(AnalysisResult).filter(AnalysisResult.run_id == run_id).count() == 0


def test_execute_run_aborted_partial_extraction_keeps_partial_result_resumable(client, create_user, monkeypatch):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    file_id = _upload_text(client, headers, task_id)
    with SessionLocal() as db:
        owner = db.query(Task).filter(Task.id == task_id).one().owner
        run = orchestrator.start_run(db, task_id, owner)
        run_id = run.id

    def fake_parse(_task_id: str, run_id: str | None = None, **_kwargs):
        with SessionLocal() as db:
            db.add(
                Evidence(
                    display_id="E-0001",
                    task_id=_task_id,
                    run_id=run_id,
                    file_id=file_id,
                    modality="text",
                    evidence_type="paragraph",
                    content="6月1日14:00，车队在地点A发现3辆车。",
                    locator_json="{}",
                    skill_id="document_parse",
                )
            )
            db.commit()
        return orchestrator.parse_service.ParseSummary(task_id=_task_id, run_id=run_id)

    class PartialAbortedExtract:
        def run(self, _context, _payload, progress_callback=None, **_kwargs):
            if progress_callback is not None:
                progress_callback(1, 1, 3)
            return SkillResult(
                success=True,
                warnings=["上游持续限流，已停止提交剩余批次（已完成 1 批、失败 1 批，共 3 批；请降低并发/减少证据后在工作台『继续分析』续跑）"],
                data={
                    "entities": [],
                    "events": [{"event_id": "EVT-001", "event_key": "车队-发现-车辆", "title": "发现车辆", "evidence_ids": ["E-0001"]}],
                    "timeline": [{"event_id": "EVT-001", "event_key": "车队-发现-车辆", "title": "发现车辆", "time_text": None, "time_normalized": None, "time_group": "时间未确定", "location": None, "time_evidence_ids": [], "evidence_ids": ["E-0001"]}],
                },
                metrics={"batch_total": 3, "batch_done": 1, "batch_failed": 1, "batch_aborted": True},
            )

    class NoConflicts:
        def run(self, *_args, **_kwargs):
            return SkillResult(success=True, data={"conflicts": []})

    class Report:
        def run(self, *_args, **_kwargs):
            return SkillResult(success=True, data={"report_markdown": "partial", "citation_check": {"invalid_citations": []}})

    monkeypatch.setattr(orchestrator.parse_service, "parse_all_files", fake_parse)
    monkeypatch.setattr(orchestrator, "IntelligenceExtractSkill", PartialAbortedExtract)
    monkeypatch.setattr(orchestrator, "ConflictDetectSkill", NoConflicts)
    monkeypatch.setattr(orchestrator, "ReportGenerateSkill", Report)

    orchestrator.execute_run(task_id, run_id)

    with SessionLocal() as db:
        run = db.get(TaskRun, run_id)
        result_count = db.query(AnalysisResult).filter(AnalysisResult.run_id == run_id).count()
        assert run.status == RUN_STATUS_SUCCEEDED
        assert run.resumable is True
        assert run.total_batches == 3
        assert run.done_batches == 1
        assert run.failed_batches == 1
        assert result_count == 1


def test_execute_run_reuses_existing_evidence_and_upserts_result_on_resume(client, create_user, monkeypatch):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    file_id = _upload_text(client, headers, task_id)
    with SessionLocal() as db:
        owner = db.query(Task).filter(Task.id == task_id).one().owner
        run = orchestrator.start_run(db, task_id, owner)
        run_id = run.id
        db.add(
            Evidence(
                display_id="E-0001",
                task_id=task_id,
                run_id=run_id,
                file_id=file_id,
                modality="text",
                evidence_type="paragraph",
                content="6月1日14:00，车队在地点A发现3辆车。",
                locator_json="{}",
                skill_id="document_parse",
            )
        )
        existing = AnalysisResult(
            task_id=task_id,
            run_id=run_id,
            entities_json="[]",
            events_json="[]",
            timeline_json="[]",
            conflicts_json="[]",
            report_markdown="old",
            citation_check_json="{}",
        )
        db.add(existing)
        db.commit()
        result_id = existing.id

    def unexpected_parse(*_args, **_kwargs):
        raise AssertionError("resume must reuse existing evidence")

    class Extract:
        def run(self, _context, _payload, **_kwargs):
            return SkillResult(
                success=True,
                data={
                    "entities": [{"type": "location", "name": "地点A", "confidence": 0.8, "evidence_ids": ["E-0001"]}],
                    "events": [{"event_id": "EVT-001", "event_key": "车队-发现-车辆", "title": "发现车辆", "evidence_ids": ["E-0001"]}],
                    "timeline": [{"event_id": "EVT-001", "event_key": "车队-发现-车辆", "title": "发现车辆", "time_text": None, "time_normalized": None, "time_group": "时间未确定", "location": None, "time_evidence_ids": [], "evidence_ids": ["E-0001"]}],
                },
                metrics={"batch_total": 1, "batch_done": 1, "batch_failed": 0},
            )

    class NoConflicts:
        def run(self, *_args, **_kwargs):
            return SkillResult(success=True, data={"conflicts": []})

    class Report:
        def run(self, *_args, **_kwargs):
            return SkillResult(success=True, data={"report_markdown": "new", "citation_check": {"invalid_citations": []}})

    monkeypatch.setattr(orchestrator.parse_service, "parse_all_files", unexpected_parse)
    monkeypatch.setattr(orchestrator, "IntelligenceExtractSkill", Extract)
    monkeypatch.setattr(orchestrator, "ConflictDetectSkill", NoConflicts)
    monkeypatch.setattr(orchestrator, "ReportGenerateSkill", Report)

    orchestrator.execute_run(task_id, run_id)

    with SessionLocal() as db:
        results = db.query(AnalysisResult).filter(AnalysisResult.run_id == run_id).all()
        run = db.get(TaskRun, run_id)
        assert len(results) == 1
        assert results[0].id == result_id
        assert results[0].report_markdown == "new"
        assert run.resumable is False
        assert run.total_batches == 1
        assert run.done_batches == 1
        assert run.failed_batches == 0


def test_execute_run_exception_marks_run_failed_terminal(client, create_user, monkeypatch):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    _upload_text(client, headers, task_id)
    with SessionLocal() as db:
        owner = db.query(Task).filter(Task.id == task_id).one().owner
        run = orchestrator.start_run(db, task_id, owner)
        run_id = run.id

    def fail_parse(_task_id: str, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(orchestrator.parse_service, "parse_all_files", fail_parse)

    orchestrator.execute_run(task_id, run_id)

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        run = db.get(TaskRun, run_id)
        assert task.status == TASK_STATUS_FAILED
        assert task.last_error == "分析失败，请查看服务日志"
        assert run.status == RUN_STATUS_FAILED
        assert run.current_step == "failed"
        assert run.error_message == "分析失败，请查看服务日志"


def test_download_report_filename_uses_result_updated_at_and_sanitizes_task_name(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers, "Bad/Name:Case*?")
    _upload_text(client, headers, task_id)
    client.post(f"/api/v1/tasks/{task_id}/runs", headers=headers)
    with SessionLocal() as db:
        result = db.query(AnalysisResult).filter(AnalysisResult.task_id == task_id).one()
        result.updated_at = datetime(2026, 6, 1, 14, 30, tzinfo=timezone.utc)
        db.commit()

    response = client.get(f"/api/v1/tasks/{task_id}/report/download", headers=headers)

    assert response.status_code == 200
    filename = unquote(response.headers["content-disposition"])
    assert "Bad_Name_Case_分析报告_20260601_1430.md" in filename


def test_full_flow_enforces_two_analyst_boundary_and_admin_access(client):
    admin_headers = login_headers(client, "admin", "admin-password")
    _admin_create_analyst(client, admin_headers, "analyst-a")
    _admin_create_analyst(client, admin_headers, "analyst-b")
    analyst_a_headers = login_headers(client, "analyst-a", "password")
    analyst_b_headers = login_headers(client, "analyst-b", "password")

    task_id = _create_task(client, analyst_a_headers, "M5 Access Case")
    _upload_text(client, analyst_a_headers, task_id)

    assert client.get(f"/api/v1/tasks/{task_id}", headers=analyst_b_headers).status_code == 404
    assert client.get(f"/api/v1/tasks/{task_id}/evidence", headers=analyst_b_headers).status_code == 404

    start_response = client.post(f"/api/v1/tasks/{task_id}/runs", headers=analyst_a_headers)
    assert start_response.status_code == 202
    run_response = client.get(f"/api/v1/tasks/{task_id}/runs/latest", headers=analyst_a_headers)
    assert run_response.status_code == 200
    assert run_response.json()["data"]["status"] == RUN_STATUS_SUCCEEDED
    assert run_response.json()["data"]["current_step"] == "awaiting_review"

    denied_after_run = client.get(f"/api/v1/tasks/{task_id}/results", headers=analyst_b_headers)
    assert denied_after_run.status_code == 404

    evidence_response = client.get(f"/api/v1/tasks/{task_id}/evidence", headers=analyst_a_headers)
    assert evidence_response.status_code == 200
    assert evidence_response.json()["data"]["total"] >= 2

    results_response = client.get(f"/api/v1/tasks/{task_id}/results", headers=analyst_a_headers)
    assert results_response.status_code == 200
    results = results_response.json()["data"]
    assert len(results["events"]) >= 2
    assert {conflict["type"] for conflict in results["conflicts"]} >= {"time", "location", "quantity"}
    assert results["citation_check"]["invalid_citations"] == []
    assert results["citation_check"]["citation_coverage"] >= 0.9

    conflict_id = results["conflicts"][0]["conflict_id"]
    patch_response = client.patch(
        f"/api/v1/tasks/{task_id}/conflicts/{conflict_id}",
        headers=analyst_a_headers,
        json={"status": "confirmed"},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["data"]["status"] == "confirmed"

    download_response = client.get(f"/api/v1/tasks/{task_id}/report/download", headers=analyst_a_headers)
    assert download_response.status_code == 200
    assert "# M5 Access Case" in download_response.text

    admin_task_response = client.get(f"/api/v1/tasks/{task_id}", headers=admin_headers)
    admin_results_response = client.get(f"/api/v1/tasks/{task_id}/results", headers=admin_headers)
    assert admin_task_response.status_code == 200
    assert admin_results_response.status_code == 200
    assert admin_results_response.json()["data"]["task_id"] == task_id
