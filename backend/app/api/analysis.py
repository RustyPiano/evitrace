import json
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models import AnalysisResult, Evidence, Task, User
from app.schemas import AppError
from app.schemas_analysis import ConflictStatusUpdate
from app.services import orchestrator, result_service
from app.services.task_service import ensure_task_access
from app.skills.base import SkillContext
from app.skills.report_generate import ReportGenerateSkill, write_latest_report

router = APIRouter(tags=["analysis"])


def _loads(value: str, default):
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _analysis_result(db: Session, task_id: str, current_user: User) -> tuple[Task, AnalysisResult]:
    task = ensure_task_access(db, task_id, current_user)
    result = db.query(AnalysisResult).filter(AnalysisResult.task_id == task.id).first()
    if result is None:
        raise AppError("TASK_NOT_FOUND", "任务不存在或无权访问", status.HTTP_404_NOT_FOUND)
    return task, result


def _evidence_payload(db: Session, task_id: str) -> list[dict]:
    evidence = db.query(Evidence).filter(Evidence.task_id == task_id).order_by(Evidence.display_id.asc()).all()
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


@router.post("/tasks/{task_id}/runs", status_code=status.HTTP_202_ACCEPTED)
def start_analysis_run(
    task_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    run = orchestrator.start_run(db, task_id, current_user)
    background_tasks.add_task(orchestrator.execute_run, task_id, run.id)
    return {"data": {"run_id": run.id, "status": "queued"}, "message": "ok"}


@router.get("/tasks/{task_id}/runs/latest")
def get_latest_run(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    run = orchestrator.latest_run(db, task_id, current_user)
    return {"data": orchestrator.serialize_run(run), "message": "ok"}


@router.get("/tasks/{task_id}/results")
def get_results(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _, result = _analysis_result(db, task_id, current_user)
    return {"data": _serialize_result(result), "message": "ok"}


@router.patch("/tasks/{task_id}/conflicts/{conflict_id}")
def update_conflict_status(
    task_id: str,
    conflict_id: str,
    payload: ConflictStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _, result = _analysis_result(db, task_id, current_user)
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    task, result = _analysis_result(db, task_id, current_user)
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
            "evidence": _evidence_payload(db, task.id),
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task, result = _analysis_result(db, task_id, current_user)
    report_path = Path(settings.data_root_path) / "tasks" / task.id / "reports" / "latest.md"
    if not report_path.is_file():
        if not result.report_markdown:
            raise AppError("TASK_NOT_FOUND", "任务不存在或无权访问", status.HTTP_404_NOT_FOUND)
        context = SkillContext(task_id=task.id, run_id=result.run_id, data_root=str(settings.data_root_path))
        write_latest_report(context, result.report_markdown)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"{task.name}_分析报告_{timestamp}.md"
    quoted = quote(filename)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"}
    return FileResponse(report_path, media_type="text/markdown; charset=utf-8", headers=headers)
