from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .constants import (
    FILE_STATUS_UPLOADED,
    RUN_STATUS_QUEUED,
    SKILL_STATUS_UNKNOWN,
    TASK_STATUS_DRAFT,
)
from .database import Base


def uuid_text() -> str:
    return uuid4().hex


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uuid_text)
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    tasks: Mapped[list["Task"]] = relationship(back_populates="owner")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uuid_text)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[str] = mapped_column(Text, ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=TASK_STATUS_DRAFT)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    owner: Mapped[User] = relationship(back_populates="tasks")
    files: Mapped[list["TaskFile"]] = relationship(back_populates="task")
    runs: Mapped[list["TaskRun"]] = relationship(back_populates="task")
    evidence_items: Mapped[list["Evidence"]] = relationship(back_populates="task")
    analysis_result: Mapped["AnalysisResult | None"] = relationship(back_populates="task")


class TaskFile(Base):
    __tablename__ = "task_files"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uuid_text)
    task_id: Mapped[str] = mapped_column(Text, ForeignKey("tasks.id"), nullable=False, index=True)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    stored_name: Mapped[str] = mapped_column(Text, nullable=False)
    extension: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    modality: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=FILE_STATUS_UPLOADED)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    task: Mapped[Task] = relationship(back_populates="files")
    evidence_items: Mapped[list["Evidence"]] = relationship(back_populates="file")


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uuid_text)
    task_id: Mapped[str] = mapped_column(Text, ForeignKey("tasks.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=RUN_STATUS_QUEUED)
    plan_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[Task] = relationship(back_populates="runs")
    analysis_results: Mapped[list["AnalysisResult"]] = relationship(back_populates="run")


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        UniqueConstraint("task_id", "display_id", name="uq_evidence_task_display_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uuid_text)
    display_id: Mapped[str] = mapped_column(Text, nullable=False)
    task_id: Mapped[str] = mapped_column(Text, ForeignKey("tasks.id"), nullable=False, index=True)
    file_id: Mapped[str] = mapped_column(Text, ForeignKey("task_files.id"), nullable=False, index=True)
    modality: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_type: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    locator_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    skill_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    task: Mapped[Task] = relationship(back_populates="evidence_items")
    file: Mapped[TaskFile] = relationship(back_populates="evidence_items")


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uuid_text)
    task_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tasks.id"), nullable=False, unique=True, index=True
    )
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("task_runs.id"), nullable=False, index=True)
    entities_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    events_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    timeline_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    conflicts_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    report_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    citation_check_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    task: Mapped[Task] = relationship(back_populates="analysis_result")
    run: Mapped[TaskRun] = relationship(back_populates="analysis_results")


class SkillConfig(Base):
    __tablename__ = "skill_configs"

    skill_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    last_status: Mapped[str] = mapped_column(Text, nullable=False, default=SKILL_STATUS_UNKNOWN)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uuid_text)
    user_id: Mapped[str | None] = mapped_column(Text, ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    detail_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


__all__ = [
    "AnalysisResult",
    "AuditLog",
    "Base",
    "Evidence",
    "SkillConfig",
    "Task",
    "TaskFile",
    "TaskRun",
    "User",
    "utc_now",
    "uuid_text",
]
