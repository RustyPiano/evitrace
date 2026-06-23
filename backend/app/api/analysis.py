import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Body, Depends, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import RUN_STATUS_QUEUED, RUN_STATUS_RUNNING
from app.dependencies import get_current_user, get_db
from app.models import AnalysisResult, Evidence, Task, TaskRun, User
from app.schemas import AppError
from app.schemas_analysis import ConflictStatusUpdate
from app.services import orchestrator, result_service
from app.services.audit_service import record_audit
from app.services.task_service import ensure_task_access
from app.skills.base import SkillContext
from app.skills.report_generate import ReportGenerateSkill, write_latest_report

router = APIRouter(tags=["analysis"])
UNSAFE_FILENAME_RE = re.compile(r"[\\/:*?\"<>|\s]+")


class RunStartRequest(BaseModel):
    confirm_large: bool = False


def _loads(value: str, default):
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _safe_filename_part(value: str | None) -> str:
    cleaned = UNSAFE_FILENAME_RE.sub("_", str(value or "").strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("._")
    return cleaned or "未命名任务"


def _analysis_result(
    db: Session,
    task_id: str,
    current_user: User,
    run_id: str | None = None,
) -> tuple[Task, AnalysisResult]:
    task = ensure_task_access(db, task_id, current_user)
    result = result_service.resolve_result(db, task.id, run_id)
    return task, result


def _evidence_payload(db: Session, result: AnalysisResult) -> list[dict]:
    evidence = (
        db.query(Evidence)
        .filter(Evidence.task_id == result.task_id, Evidence.run_id == result.run_id)
        .order_by(Evidence.display_id.asc())
        .all()
    )
    return [
        {
            "id": item.id,
            "display_id": item.display_id,
            "content": item.content,
            "content_summary": item.content[:240],
            "file": {
                "id": item.file.id,
                "original_name": item.file.original_name,
                "stored_name": item.file.stored_name,
                "extension": item.file.extension,
                "mime_type": item.file.mime_type,
                "size_bytes": item.file.size_bytes,
                "modality": item.file.modality,
                "status": item.file.status,
                "error_message": item.file.error_message,
            },
            "locator": result_service.deserialize_locator(item.locator_json),
        }
        for item in evidence
    ]


def _serialize_result(result: AnalysisResult) -> dict:
    return {
        "id": result.id,
        "task_id": result.task_id,
        "run_id": result.run_id,
        "entities": _loads(result.entities_json, []),
        "events": _loads(result.events_json, []),
        "timeline": _loads(result.timeline_json, []),
        "conflicts": _loads(result.conflicts_json, []),
        "report_markdown": result.report_markdown,
        "citation_check": _loads(result.citation_check_json, {}),
        "created_at": result.created_at.isoformat() if result.created_at else None,
        "updated_at": result.updated_at.isoformat() if result.updated_at else None,
    }


def _serialize_run_summary(run: TaskRun, has_result: bool) -> dict:
    return {
        "run_id": run.id,
        "status": run.status,
        "progress": run.progress,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "has_result": has_result,
    }


@router.post("/tasks/{task_id}/runs", status_code=status.HTTP_202_ACCEPTED)
def start_analysis_run(
    task_id: str,
    background_tasks: BackgroundTasks,
    payload: RunStartRequest = Body(default=RunStartRequest()),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    run = orchestrator.start_run(db, task_id, current_user, confirm_large=payload.confirm_large)
    record_audit(
        db,
        user_id=current_user.id,
        action="analysis_started",
        resource_type="task",
        resource_id=task_id,
        detail={"run_id": run.id, "confirm_large": payload.confirm_large},
    )
    db.commit()
    background_tasks.add_task(orchestrator.execute_run, task_id, run.id)
    return {"data": {"run_id": run.id, "status": "queued"}, "message": "ok"}


@router.post("/tasks/{task_id}/runs/{run_id}/resume", status_code=status.HTTP_202_ACCEPTED)
def resume_analysis_run(
    task_id: str,
    run_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    run = orchestrator.resume_run(db, task_id, run_id, current_user)
    record_audit(
        db,
        user_id=current_user.id,
        action="analysis_resumed",
        resource_type="task",
        resource_id=task_id,
        detail={"run_id": run.id},
    )
    db.commit()
    background_tasks.add_task(orchestrator.execute_run, task_id, run.id)
    return {"data": {"run_id": run.id, "status": "queued"}, "message": "ok"}


@router.post("/tasks/{task_id}/runs/cancel")
def cancel_analysis_run(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    task = ensure_task_access(db, task_id, current_user)
    run = (
        db.query(TaskRun)
        .filter(TaskRun.task_id == task.id, TaskRun.status.in_([RUN_STATUS_QUEUED, RUN_STATUS_RUNNING]))
        .order_by(TaskRun.started_at.desc().nullslast(), TaskRun.id.desc())
        .first()
    )
    if run is None:
        raise AppError("NO_RUNNING_RUN", "当前没有正在运行的分析", status.HTTP_409_CONFLICT)

    run.cancel_requested = True
    record_audit(
        db,
        user_id=current_user.id,
        action="analysis_cancel_requested",
        resource_type="task",
        resource_id=task.id,
        detail={"run_id": run.id},
    )
    db.commit()
    return {"data": {"run_id": run.id, "cancel_requested": True}, "message": "正在停止分析"}


@router.get("/tasks/{task_id}/runs/latest")
def get_latest_run(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    run = orchestrator.latest_run(db, task_id, current_user)
    return {"data": orchestrator.serialize_run(run), "message": "ok"}


@router.get("/tasks/{task_id}/runs")
def list_runs(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    task = ensure_task_access(db, task_id, current_user)
    result_run_ids = {
        row[0]
        for row in db.query(AnalysisResult.run_id).filter(AnalysisResult.task_id == task.id).all()
    }
    runs = (
        db.query(TaskRun)
        .filter(TaskRun.task_id == task.id)
        .order_by(TaskRun.started_at.desc().nullslast(), TaskRun.finished_at.desc().nullslast())
        .all()
    )
    return {
        "data": [_serialize_run_summary(run, run.id in result_run_ids) for run in runs],
        "message": "ok",
    }


@router.get("/tasks/{task_id}/results")
def get_results(
    task_id: str,
    run_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _, result = _analysis_result(db, task_id, current_user, run_id)
    return {"data": _serialize_result(result), "message": "ok"}


@router.patch("/tasks/{task_id}/conflicts/{conflict_id}")
def update_conflict_status(
    task_id: str,
    conflict_id: str,
    payload: ConflictStatusUpdate,
    run_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _, result = _analysis_result(db, task_id, current_user, run_id)
    conflicts = _loads(result.conflicts_json, [])
    for conflict in conflicts:
        if conflict.get("conflict_id") == conflict_id:
            conflict["status"] = payload.status
            result.conflicts_json = _dumps(conflicts)
            db.commit()
            return {"data": conflict, "message": "ok"}
    raise AppError("TASK_NOT_FOUND", "任务不存在或无权访问", status.HTTP_404_NOT_FOUND)


@router.post("/tasks/{task_id}/report/regenerate")
def regenerate_report(
    task_id: str,
    run_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    task, result = _analysis_result(db, task_id, current_user, run_id)
    context = SkillContext(task_id=task.id, run_id=result.run_id, data_root=str(settings.data_root_path))
    report_result = ReportGenerateSkill().run(
        context,
        {
            "task": {
                "id": task.id,
                "name": task.name,
                "objective": task.objective,
                "description": task.description,
            },
            "evidence": _evidence_payload(db, result),
            "entities": _loads(result.entities_json, []),
            "events": _loads(result.events_json, []),
            "timeline": _loads(result.timeline_json, []),
            "conflicts": _loads(result.conflicts_json, []),
        },
    )
    result.report_markdown = report_result.data["report_markdown"]
    result.citation_check_json = _dumps(report_result.data["citation_check"])
    db.commit()
    return {
        "data": {
            "report_markdown": result.report_markdown,
            "citation_check": report_result.data["citation_check"],
            "warnings": report_result.warnings,
        },
        "message": "ok",
    }


@router.get("/tasks/{task_id}/report/download")
def download_report(
    task_id: str,
    run_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task, result = _analysis_result(db, task_id, current_user, run_id)
    reports_dir = Path(settings.data_root_path) / "tasks" / task.id / "reports"
    report_path = reports_dir / ("latest.md" if run_id is None else f"{result.run_id}.md")
    if not report_path.is_file():
        if not result.report_markdown:
            raise AppError("TASK_NOT_FOUND", "任务不存在或无权访问", status.HTTP_404_NOT_FOUND)
        if run_id is None:
            context = SkillContext(task_id=task.id, run_id=result.run_id, data_root=str(settings.data_root_path))
            write_latest_report(context, result.report_markdown)
        else:
            reports_dir.mkdir(parents=True, exist_ok=True)
            report_path.write_text(result.report_markdown, encoding="utf-8")

    report_time = result.updated_at or result.created_at or datetime.now()
    timestamp = report_time.strftime("%Y%m%d_%H%M")
    filename = f"{_safe_filename_part(task.name)}_分析报告_{timestamp}.md"
    quoted = quote(filename)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"}
    record_audit(
        db,
        user_id=current_user.id,
        action="report_downloaded",
        resource_type="task",
        resource_id=task.id,
        detail={"filename": filename},
    )
    db.commit()
    return FileResponse(report_path, media_type="text/markdown; charset=utf-8", headers=headers)
