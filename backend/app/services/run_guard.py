from contextlib import contextmanager
from threading import Lock
from typing import Iterator

from fastapi import status
from sqlalchemy.orm import Session

from app.constants import RUN_STATUS_RUNNING, TASK_RUNNING_STATUSES
from app.models import Task, TaskRun
from app.schemas import AppError

_START_LOCK = Lock()


@contextmanager
def single_run_start_lock() -> Iterator[None]:
    with _START_LOCK:
        yield


def is_any_task_or_run_active(db: Session) -> bool:
    active_task = (
        db.query(Task.id)
        .filter(Task.status.in_(TASK_RUNNING_STATUSES))
        .first()
    )
    if active_task is not None:
        return True

    active_run = db.query(TaskRun.id).filter(TaskRun.status == RUN_STATUS_RUNNING).first()
    return active_run is not None


def ensure_no_active_run(db: Session) -> None:
    if is_any_task_or_run_active(db):
        raise AppError("TASK_ALREADY_RUNNING", "已有任务运行", status.HTTP_409_CONFLICT)
