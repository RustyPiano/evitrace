from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.constants import TASK_RUNNING_STATUSES, TASK_STATUS_PARSING
from app.models import TaskFile, User
from app.schemas import AppError
from app.services import parse_service
from app.schemas import TaskCreate, TaskUpdate
from app.services import task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("")
def list_tasks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return {"data": task_service.list_tasks(db, current_user), "message": "ok"}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return {"data": task_service.create_task(db, payload, current_user), "message": "ok"}


@router.get("/{task_id}")
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return {"data": task_service.get_task_detail(db, task_id, current_user), "message": "ok"}


@router.patch("/{task_id}")
def update_task(
    task_id: str,
    payload: TaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return {
        "data": task_service.update_task(db, task_id, payload, current_user),
        "message": "ok",
    }


@router.delete("/{task_id}")
def delete_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    task_service.delete_task(db, task_id, current_user)
    return {"data": {"id": task_id}, "message": "ok"}


@router.post("/{task_id}/parse", status_code=status.HTTP_202_ACCEPTED)
def parse_task_files(
    task_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    task = task_service.ensure_task_access(db, task_id, current_user)
    if task.status in TASK_RUNNING_STATUSES:
        raise AppError("TASK_ALREADY_RUNNING", "已有任务运行", status.HTTP_409_CONFLICT)
    file_count = db.query(TaskFile).filter(TaskFile.task_id == task.id).count()
    if file_count == 0:
        raise AppError("TASK_NOT_READY", "无可分析文件", status.HTTP_409_CONFLICT)

    task.status = TASK_STATUS_PARSING
    task.last_error = None
    db.commit()
    background_tasks.add_task(parse_service.parse_all_files, task.id)
    return {"data": {"task_id": task.id, "status": TASK_STATUS_PARSING}, "message": "ok"}
