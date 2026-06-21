import json

from app.database import SessionLocal
from app.models import Evidence, Task, TaskFile, User
from app.services import result_service


def _insert_task_with_file(owner: User) -> tuple[str, str]:
    with SessionLocal() as db:
        task = Task(name="Case", objective="Objective", owner_id=owner.id, status="ready")
        db.add(task)
        db.flush()
        file = TaskFile(
            task_id=task.id,
            original_name="note.txt",
            stored_name="file.txt",
            extension="txt",
            mime_type="text/plain",
            size_bytes=12,
            modality="text",
        )
        db.add(file)
        db.commit()
        return task.id, file.id


def test_create_evidence_batch_assigns_incrementing_display_ids(create_user):
    owner = create_user("owner")
    task_id, file_id = _insert_task_with_file(owner)

    with SessionLocal() as db:
        first = result_service.create_evidence_batch(
            db,
            task_id,
            [
                {
                    "file_id": file_id,
                    "content": "Alpha",
                    "modality": "text",
                    "evidence_type": "paragraph",
                    "locator": {"kind": "text", "page": None, "paragraph": 1},
                    "confidence": None,
                    "skill_id": "document_parse",
                },
                {
                    "file_id": file_id,
                    "content": "Beta",
                    "modality": "text",
                    "evidence_type": "paragraph",
                    "locator": {"kind": "text", "page": None, "paragraph": 2},
                    "confidence": None,
                    "skill_id": "document_parse",
                },
            ],
        )
        second = result_service.create_evidence_batch(
            db,
            task_id,
            [
                {
                    "file_id": file_id,
                    "content": "Gamma",
                    "modality": "text",
                    "evidence_type": "paragraph",
                    "locator": {"kind": "text", "page": None, "paragraph": 3},
                    "confidence": None,
                    "skill_id": "document_parse",
                }
            ],
        )
        db.commit()

    assert [item.display_id for item in first] == ["E-0001", "E-0002"]
    assert [item.display_id for item in second] == ["E-0003"]
    with SessionLocal() as db:
        display_ids = [row.display_id for row in db.query(Evidence).order_by(Evidence.display_id)]
    assert display_ids == ["E-0001", "E-0002", "E-0003"]


def test_evidence_queries_are_limited_to_owner_or_admin(create_user):
    owner = create_user("owner")
    other = create_user("other")
    admin = create_user("admin-user", role="admin")
    task_id, file_id = _insert_task_with_file(owner)
    with SessionLocal() as db:
        result_service.create_evidence_batch(
            db,
            task_id,
            [
                {
                    "file_id": file_id,
                    "content": "Secret",
                    "modality": "text",
                    "evidence_type": "paragraph",
                    "locator": {"kind": "text", "page": None},
                    "confidence": None,
                    "skill_id": "document_parse",
                }
            ],
        )
        db.commit()

    with SessionLocal() as db:
        assert result_service.list_task_evidence(db, task_id, owner)["total"] == 1
        assert result_service.list_task_evidence(db, task_id, admin)["total"] == 1
        try:
            result_service.list_task_evidence(db, task_id, other)
        except Exception as exc:
            assert getattr(exc, "code") == "TASK_NOT_FOUND"
        else:
            raise AssertionError("other user should not see evidence")


def test_locator_helpers_round_trip_json():
    locator = {"kind": "audio", "start_ms": 100, "end_ms": 900}
    encoded = result_service.serialize_locator(locator)

    assert json.loads(encoded) == locator
    assert result_service.deserialize_locator(encoded) == locator
