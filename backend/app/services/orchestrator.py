import json
import logging
from datetime import datetime
from typing import Any

from fastapi import status
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import (
    RUN_STATUS_FAILED,
    RUN_STATUS_QUEUED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCEEDED,
    TASK_RUNNING_STATUSES,
    TASK_STATUS_AWAITING_REVIEW,
    TASK_STATUS_DETECTING_CONFLICTS,
    TASK_STATUS_EXTRACTING,
    TASK_STATUS_FAILED,
    TASK_STATUS_GENERATING_REPORT,
    TASK_STATUS_PARSING,
    TASK_STATUS_QUEUED,
)
from app.database import SessionLocal
from app.models import AnalysisResult, Evidence, ExtractionBatch, Task, TaskFile, TaskRun, utc_now
from app.schemas import AppError
from app.services import parse_service, result_service, run_guard
from app.services.storage_service import PARSER_SKILL_BY_MODALITY
from app.services.task_service import ensure_task_access, serialize_file, task_not_found
from app.skills.base import RunCancelled, SkillContext
from app.skills.conflict_detect import ConflictDetectSkill
from app.skills.intelligence_extract import IntelligenceExtractSkill
from app.skills.registry import SKILL_MANIFESTS, is_enabled
from app.skills.report_generate import ReportGenerateSkill

logger = logging.getLogger(__name__)
INTERRUPTED_MESSAGE = "服务重启导致运行中断，请重新执行"
REQUIRED_ANALYSIS_SKILLS = ["intelligence_extract", "conflict_detect", "report_generate"]
CANCELLED_MESSAGE = "分析已手动取消"


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_load(value: str, default: Any) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _now() -> datetime:
    from app.models import utc_now

    return utc_now()


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, AppError):
        return exc.message
    return "分析失败，请查看服务日志"


def _force_fail_unfinished_run(task_id: str, run_id: str, message: str) -> None:
    with SessionLocal() as db:
        run = db.get(TaskRun, run_id)
        task = db.get(Task, task_id)
        changed = False
        if run is not None and run.status in {RUN_STATUS_QUEUED, RUN_STATUS_RUNNING}:
            run.status = RUN_STATUS_FAILED
            run.error_message = message
            run.finished_at = _now()
            run.current_step = "failed"
            changed = True
        if task is not None and task.status in TASK_RUNNING_STATUSES:
            task.status = TASK_STATUS_FAILED
            task.last_error = message
            changed = True
        if changed:
            db.commit()


def _run_cancel_requested(run_id: str) -> bool:
    with SessionLocal() as db:
        run = db.get(TaskRun, run_id)
        return bool(run and run.cancel_requested)


def _build_plan(run_id: str, files: list[TaskFile]) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    order = 1
    for skill_id in ("document_parse", "image_ocr", "audio_transcribe", "video_parse"):
        file_ids = [file.id for file in files if PARSER_SKILL_BY_MODALITY.get(file.modality) == skill_id]
        if not file_ids:
            continue
        steps.append({"order": order, "skill": skill_id, "file_ids": file_ids})
        order += 1
    for skill_id in REQUIRED_ANALYSIS_SKILLS + ["citation_validate"]:
        steps.append({"order": order, "skill": skill_id})
        order += 1
    return {"run_id": run_id, "steps": steps}


def _ensure_required_skills_enabled(db: Session) -> None:
    required_ids = {manifest.id for manifest in SKILL_MANIFESTS if manifest.required}
    required_ids.update(REQUIRED_ANALYSIS_SKILLS)
    for skill_id in sorted(required_ids):
        if not is_enabled(db, skill_id):
            raise AppError(
                "REQUIRED_SKILL_UNAVAILABLE",
                f"必需 Skill 不可用: {skill_id}",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )


def _delete_previous_outputs(db: Session, task_id: str) -> None:
    db.query(Evidence).filter(Evidence.task_id == task_id).delete()
    db.query(AnalysisResult).filter(AnalysisResult.task_id == task_id).delete()


def _warnings(run: TaskRun) -> list[str]:
    value = _json_load(run.warnings_json, [])
    return value if isinstance(value, list) else []


def _set_warnings(run: TaskRun, warnings: list[str]) -> None:
    run.warnings_json = _json_dump(warnings)


def _update_state(
    db: Session,
    task: Task,
    run: TaskRun,
    *,
    task_status: str,
    run_status: str | None = None,
    progress: int | None = None,
    current_step: str | None = None,
) -> None:
    task.status = task_status
    task.last_error = None
    if run_status is not None:
        run.status = run_status
    if progress is not None:
        run.progress = max(run.progress, progress)
    if current_step is not None:
        run.current_step = current_step
    db.commit()
    logger.info(
        "Task run progress task_id=%s run_id=%s task_status=%s run_status=%s progress=%s step=%s",
        task.id,
        run.id,
        task.status,
        run.status,
        run.progress,
        run.current_step,
    )


def _serialize_evidence_for_analysis(evidence: Evidence) -> dict[str, Any]:
    return {
        "id": evidence.id,
        "display_id": evidence.display_id,
        "content": evidence.content,
        "content_summary": evidence.content[:240],
        "file": serialize_file(evidence.file),
        "locator": result_service.deserialize_locator(evidence.locator_json),
        "modality": evidence.modality,
        "evidence_type": evidence.evidence_type,
    }


def _list_evidence(db: Session, run_id: str) -> list[dict[str, Any]]:
    rows = db.query(Evidence).filter(Evidence.run_id == run_id).order_by(Evidence.display_id.asc()).all()
    return [_serialize_evidence_for_analysis(row) for row in rows]


class _RunBatchPersistence:
    def __init__(self, db: Session, run_id: str) -> None:
        self.db = db
        self.run_id = run_id

    def load_done(self) -> dict[int, tuple[str, dict]]:
        rows = (
            self.db.query(ExtractionBatch)
            .filter(ExtractionBatch.run_id == self.run_id, ExtractionBatch.status == "done")
            .all()
        )
        done: dict[int, tuple[str, dict]] = {}
        for row in rows:
            if row.result_json is None:
                continue
            done[row.batch_index] = (row.input_hash, _json_load(row.result_json, {}))
        return done

    def record_batch(
        self,
        batch_index: int,
        input_hash: str,
        status: str,
        result: dict | None,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        row = (
            self.db.query(ExtractionBatch)
            .filter(ExtractionBatch.run_id == self.run_id, ExtractionBatch.batch_index == batch_index)
            .one_or_none()
        )
        result_json = _json_dump(result) if result is not None else None
        if row is None:
            row = ExtractionBatch(
                run_id=self.run_id,
                batch_index=batch_index,
                input_hash=input_hash,
                status=status,
                attempt_count=1,
                result_json=result_json,
                error_code=error_code,
                error_message=error_message,
            )
            self.db.add(row)
        else:
            row.input_hash = input_hash
            row.status = status
            row.attempt_count += 1
            row.result_json = result_json
            row.error_code = error_code
            row.error_message = error_message
            row.updated_at = utc_now()
        self.db.commit()

    def set_plan(self, total_batches: int, estimated_input_tokens: int) -> None:
        run = self.db.get(TaskRun, self.run_id)
        if run is None:
            return
        run.total_batches = total_batches
        run.estimated_input_tokens = estimated_input_tokens
        self.db.commit()


def _task_payload(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "name": task.name,
        "objective": task.objective,
        "description": task.description,
        "status": task.status,
    }


def start_run(db: Session, task_id: str, current_user, confirm_large: bool = False) -> TaskRun:
    with run_guard.single_run_start_lock():
        task = ensure_task_access(db, task_id, current_user)
        file_count = db.query(TaskFile).filter(TaskFile.task_id == task.id).count()
        if file_count == 0:
            raise AppError("TASK_NOT_READY", "无可分析文件", status.HTTP_409_CONFLICT)
        threshold = settings.extract_max_files_confirm
        if threshold > 0 and file_count > threshold and not confirm_large:
            raise AppError(
                "RUN_TOO_LARGE",
                f"本次包含 {file_count} 个文件，超过确认阈值 {threshold}，"
                f"真实分析可能产生大量模型调用与费用。如确认继续，请再次确认。",
                status.HTTP_409_CONFLICT,
            )
        if task.status in TASK_RUNNING_STATUSES:
            raise AppError("TASK_ALREADY_RUNNING", "已有任务运行", status.HTTP_409_CONFLICT)
        run_guard.ensure_no_active_run(db)
        _ensure_required_skills_enabled(db)
        files = db.query(TaskFile).filter(TaskFile.task_id == task.id).order_by(TaskFile.created_at.asc()).all()
        run = TaskRun(
            task_id=task.id,
            status=RUN_STATUS_QUEUED,
            progress=0,
            current_step="queued",
            warnings_json="[]",
            cancel_requested=False,
            started_at=_now(),
        )
        db.add(run)
        db.flush()
        run.plan_json = _json_dump(_build_plan(run.id, files))
        task.status = TASK_STATUS_QUEUED
        task.last_error = None
        db.commit()
        db.refresh(run)
        return run


def resume_run(db: Session, task_id: str, run_id: str, current_user) -> TaskRun:
    with run_guard.single_run_start_lock():
        task = ensure_task_access(db, task_id, current_user)
        run = db.get(TaskRun, run_id)
        if run is None or run.task_id != task.id:
            raise AppError("TASK_NOT_FOUND", "任务不存在或无权访问", status.HTTP_404_NOT_FOUND)
        if not run.resumable:
            raise AppError("RUN_NOT_RESUMABLE", "该运行不可续跑", status.HTTP_409_CONFLICT)
        if task.status in TASK_RUNNING_STATUSES:
            raise AppError("TASK_ALREADY_RUNNING", "已有任务运行", status.HTTP_409_CONFLICT)
        run_guard.ensure_no_active_run(db)
        _ensure_required_skills_enabled(db)
        run.status = RUN_STATUS_QUEUED
        run.current_step = "queued"
        run.cancel_requested = False
        run.error_message = None
        run.finished_at = None
        run.started_at = _now()
        # 重置展示型执行字段，避免续跑时进度被 _update_state 的 max() 卡在旧值、
        # 或在重新进入抽取前短暂暴露过期批次计数。保留 resumable 与已有 extraction_batches。
        run.progress = 0
        run.total_batches = 0
        run.done_batches = 0
        run.failed_batches = 0
        run.estimated_input_tokens = 0
        task.status = TASK_STATUS_QUEUED
        task.last_error = None
        db.commit()
        db.refresh(run)
        return run


def _create_run_without_user(db: Session, task_id: str) -> TaskRun:
    task = db.get(Task, task_id)
    if task is None:
        raise task_not_found()
    file_count = db.query(TaskFile).filter(TaskFile.task_id == task.id).count()
    if file_count == 0:
        raise AppError("TASK_NOT_READY", "无可分析文件", status.HTTP_409_CONFLICT)
    run_guard.ensure_no_active_run(db)
    _ensure_required_skills_enabled(db)
    files = db.query(TaskFile).filter(TaskFile.task_id == task.id).order_by(TaskFile.created_at.asc()).all()
    run = TaskRun(
        task_id=task.id,
        status=RUN_STATUS_QUEUED,
        progress=0,
        current_step="queued",
        warnings_json="[]",
        cancel_requested=False,
        started_at=_now(),
    )
    db.add(run)
    db.flush()
    run.plan_json = _json_dump(_build_plan(run.id, files))
    task.status = TASK_STATUS_QUEUED
    task.last_error = None
    db.commit()
    db.refresh(run)
    return run


def run_task(task_id: str, run_id: str | None = None) -> None:
    if run_id is None:
        with run_guard.single_run_start_lock(), SessionLocal() as db:
            run = _create_run_without_user(db, task_id)
            run_id = run.id
    execute_run(task_id, run_id)


def execute_run(task_id: str, run_id: str) -> None:
    warnings: list[str] = []
    final_error_message = "分析任务异常中断"
    cancel_check = lambda: _run_cancel_requested(run_id)
    try:
        with SessionLocal() as db:
            task = db.get(Task, task_id)
            run = db.get(TaskRun, run_id)
            if task is None or run is None:
                return
            if cancel_check():
                raise RunCancelled()
            _update_state(
                db,
                task,
                run,
                task_status=TASK_STATUS_QUEUED,
                run_status=RUN_STATUS_RUNNING,
                progress=0,
                current_step="queued",
            )
            if cancel_check():
                raise RunCancelled()

            # 续跑优化：该 run 已有证据则跳过解析、直接复用。绝大多数中断发生在抽取阶段
            # （已被批级续跑覆盖），那时证据是完整的。已知边界：若上次恰好在解析中途中断、
            # 只写入了部分证据，续跑会按这部分残缺证据继续——可点「重新分析」走全新一轮规避。
            existing_evidence_count = db.query(Evidence).filter(Evidence.run_id == run.id).count()
            if existing_evidence_count > 0:
                logger.info("resume: reuse %s evidence for run_id=%s", existing_evidence_count, run.id)
                _update_state(db, task, run, task_status=TASK_STATUS_PARSING, progress=45, current_step="parsing")
            else:
                _update_state(db, task, run, task_status=TASK_STATUS_PARSING, progress=10, current_step="parsing")
                parse_summary = parse_service.parse_all_files(
                    task_id,
                    run_id=run.id,
                    progress_start=10,
                    progress_end=45,
                    cancel_check=cancel_check,
                )
                warnings.extend(parse_summary.warnings)
                warnings.extend(parse_summary.errors)
                _update_state(db, task, run, task_status=TASK_STATUS_PARSING, progress=45, current_step="parsing")
            if cancel_check():
                raise RunCancelled()

            evidence_items = _list_evidence(db, run.id)
            if not evidence_items:
                raise AppError(
                    "ANALYSIS_FAILED",
                    "没有生成可分析证据",
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            _update_state(db, task, run, task_status=TASK_STATUS_EXTRACTING, progress=55, current_step="extracting")
            context = SkillContext(task_id=task.id, run_id=run.id, data_root=str(settings.data_root_path))
            def extract_progress(done: int, failed: int, total: int) -> None:
                processed = done + failed
                progress = min(70, 55 + int(15 * processed / max(total, 1)))
                run.total_batches = total
                run.done_batches = done
                run.failed_batches = failed
                suffix = f" 失败{failed}" if failed else ""
                _update_state(
                    db,
                    task,
                    run,
                    task_status=TASK_STATUS_EXTRACTING,
                    progress=progress,
                    current_step=f"extracting {processed}/{total}{suffix}",
                )

            extract_result = IntelligenceExtractSkill().run(
                context,
                {"task": _task_payload(task), "evidence": evidence_items},
                progress_callback=extract_progress,
                cancel_check=cancel_check,
                persistence=_RunBatchPersistence(db, run.id),
            )
            if not extract_result.success:
                raise AppError(
                    "ANALYSIS_FAILED",
                    "; ".join(extract_result.errors) or "要素提取失败",
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            warnings.extend(extract_result.warnings)
            batch_total = int(extract_result.metrics.get("batch_total") or 0)
            batch_done = int(extract_result.metrics.get("batch_done") or 0)
            batch_failed = int(extract_result.metrics.get("batch_failed") or 0)
            batch_aborted = bool(extract_result.metrics.get("batch_aborted"))
            run.total_batches = batch_total
            run.done_batches = batch_done
            run.failed_batches = batch_failed
            if batch_done == 0 and batch_total > 0:
                run.resumable = True
                _set_warnings(run, warnings)
                db.commit()
                raise AppError(
                    "ANALYSIS_FAILED",
                    "全部抽取批次失败，可在工作台续跑",
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            run.resumable = batch_done > 0 and (batch_failed > 0 or batch_aborted)
            db.commit()
            entities = extract_result.data["entities"]
            events = extract_result.data["events"]
            timeline = extract_result.data["timeline"]
            _update_state(db, task, run, task_status=TASK_STATUS_EXTRACTING, progress=70, current_step="extracting")
            if cancel_check():
                raise RunCancelled()

            _update_state(
                db,
                task,
                run,
                task_status=TASK_STATUS_DETECTING_CONFLICTS,
                progress=80,
                current_step="detecting_conflicts",
            )
            conflict_result = ConflictDetectSkill().run(context, {"events": events})
            warnings.extend(conflict_result.warnings)
            conflicts = conflict_result.data["conflicts"]
            if cancel_check():
                raise RunCancelled()

            _update_state(
                db,
                task,
                run,
                task_status=TASK_STATUS_GENERATING_REPORT,
                progress=90,
                current_step="generating_report",
            )
            report_result = ReportGenerateSkill().run(
                context,
                {
                    "task": _task_payload(task),
                    "evidence": evidence_items,
                    "entities": entities,
                    "events": events,
                    "timeline": timeline,
                    "conflicts": conflicts,
                },
            )
            warnings.extend(report_result.warnings)
            report_markdown = report_result.data["report_markdown"]
            citation_check = report_result.data["citation_check"]

            result = db.query(AnalysisResult).filter(AnalysisResult.run_id == run.id).one_or_none()
            if result is None:
                result = AnalysisResult(task_id=task.id, run_id=run.id)
                db.add(result)
            result.entities_json = _json_dump(entities)
            result.events_json = _json_dump(events)
            result.timeline_json = _json_dump(timeline)
            result.conflicts_json = _json_dump(conflicts)
            result.report_markdown = report_markdown
            result.citation_check_json = _json_dump(citation_check)
            _set_warnings(run, warnings)
            run.finished_at = _now()
            _update_state(
                db,
                task,
                run,
                task_status=TASK_STATUS_AWAITING_REVIEW,
                run_status=RUN_STATUS_SUCCEEDED,
                progress=100,
                current_step="awaiting_review",
            )
    except RunCancelled:
        final_error_message = CANCELLED_MESSAGE
        logger.info("Task background run cancelled task_id=%s run_id=%s", task_id, run_id)
        with SessionLocal() as db:
            run = db.get(TaskRun, run_id)
            task = db.get(Task, task_id)
            if run is not None:
                run.status = RUN_STATUS_FAILED
                run.error_message = final_error_message
                run.finished_at = _now()
                run.current_step = "cancelled"
                run.resumable = True
                _set_warnings(run, warnings)
            if task is not None:
                task.status = TASK_STATUS_FAILED
                task.last_error = final_error_message
            db.commit()
    except Exception as exc:
        final_error_message = _safe_error(exc)
        logger.exception("Task background run crashed task_id=%s run_id=%s error=%s", task_id, run_id, type(exc).__name__)
        with SessionLocal() as db:
            run = db.get(TaskRun, run_id)
            task = db.get(Task, task_id)
            if run is not None:
                run.status = RUN_STATUS_FAILED
                run.error_message = final_error_message
                run.finished_at = _now()
                run.current_step = "failed"
                if run.total_batches > 0 or run.done_batches > 0 or run.failed_batches > 0:
                    run.resumable = True
                _set_warnings(run, warnings)
            if task is not None:
                task.status = TASK_STATUS_FAILED
                task.last_error = final_error_message
            db.commit()
    finally:
        _force_fail_unfinished_run(task_id, run_id, final_error_message)


def recover_interrupted_runs() -> None:
    with SessionLocal() as db:
        runs = (
            db.query(TaskRun)
            .filter(TaskRun.status.in_([RUN_STATUS_QUEUED, RUN_STATUS_RUNNING]))
            .all()
        )
        for run in runs:
            run.status = RUN_STATUS_FAILED
            run.error_message = INTERRUPTED_MESSAGE
            run.finished_at = _now()
            run.current_step = "failed"
            run.resumable = True
            task = db.get(Task, run.task_id)
            if task is not None and task.status in TASK_RUNNING_STATUSES:
                task.status = TASK_STATUS_FAILED
                task.last_error = INTERRUPTED_MESSAGE
        db.commit()


def latest_run(db: Session, task_id: str, current_user) -> TaskRun:
    task = ensure_task_access(db, task_id, current_user)
    run = (
        db.query(TaskRun)
        .filter(TaskRun.task_id == task.id)
        .order_by(TaskRun.started_at.desc())
        .first()
    )
    if run is None:
        raise AppError("TASK_NOT_FOUND", "任务不存在或无权访问", status.HTTP_404_NOT_FOUND)
    return run


def serialize_run(run: TaskRun) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "status": run.status,
        "plan_json": _json_load(run.plan_json, {}),
        "progress": run.progress,
        "current_step": run.current_step,
        "warnings": _warnings(run),
        "error_message": run.error_message,
        "resumable": run.resumable,
        "total_batches": run.total_batches,
        "done_batches": run.done_batches,
        "failed_batches": run.failed_batches,
        "estimated_input_tokens": run.estimated_input_tokens,
    }
