import pytest
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import Evidence, Task, TaskFile, User
from app.services.auth_service import hash_password


def test_username_unique_constraint_is_enforced():
    with SessionLocal() as db:
        db.add(
            User(
                username="duplicate",
                password_hash=hash_password("password"),
                role="analyst",
            )
        )
        db.commit()
        db.add(
            User(
                username="duplicate",
                password_hash=hash_password("password"),
                role="analyst",
            )
        )

        with pytest.raises(IntegrityError):
            db.commit()


def test_evidence_display_id_is_unique_within_task():
    with SessionLocal() as db:
        owner = User(
            username="owner",
            password_hash=hash_password("password"),
            role="analyst",
        )
        db.add(owner)
        db.commit()
        db.refresh(owner)
        task = Task(name="Case", objective="Objective", owner_id=owner.id, status="draft")
        db.add(task)
        db.commit()
        db.refresh(task)
        task_file = TaskFile(
            task_id=task.id,
            original_name="note.txt",
            stored_name="abc.txt",
            extension="txt",
            mime_type="text/plain",
            size_bytes=4,
            modality="text",
            status="uploaded",
        )
        db.add(task_file)
        db.commit()
        db.refresh(task_file)
        db.add(
            Evidence(
                display_id="E-0001",
                task_id=task.id,
                file_id=task_file.id,
                modality="text",
                evidence_type="paragraph",
                content="first",
                locator_json="{}",
                skill_id="document_parse",
            )
        )
        db.add(
            Evidence(
                display_id="E-0001",
                task_id=task.id,
                file_id=task_file.id,
                modality="text",
                evidence_type="paragraph",
                content="second",
                locator_json="{}",
                skill_id="document_parse",
            )
        )

        with pytest.raises(IntegrityError):
            db.commit()
