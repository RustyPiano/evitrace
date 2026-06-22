from io import BytesIO

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import Evidence, SkillConfig, Task, TaskFile, TaskRun
from app.services import parse_service
from app.skills.base import SkillResult

from tests.conftest import login_headers


def _create_task(client, headers) -> str:
    response = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"name": "M2 Case", "objective": "Parse evidence"},
    )
    assert response.status_code == 201
    return response.json()["data"]["id"]


def _png_bytes() -> bytes:
    from PIL import Image

    buffer = BytesIO()
    image = Image.new("RGB", (32, 20), color=(255, 255, 255))
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _docx_bytes() -> bytes:
    from docx import Document

    buffer = BytesIO()
    document = Document()
    document.add_paragraph("DOCX evidence paragraph")
    document.save(buffer)
    return buffer.getvalue()


def _pdf_bytes() -> bytes:
    import fitz

    pdf = fitz.open()
    first = pdf.new_page()
    first.insert_text((72, 72), "PDF first page")
    second = pdf.new_page()
    second.insert_text((72, 72), "PDF second page")
    data = pdf.tobytes()
    pdf.close()
    return data


def _upload_mixed_files(client, headers, task_id: str) -> list[dict]:
    response = client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[
            ("files", ("note.txt", b"TXT paragraph one\n\nTXT paragraph two", "text/plain")),
            ("files", ("report.pdf", _pdf_bytes(), "application/pdf")),
            (
                "files",
                (
                    "report.docx",
                    _docx_bytes(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            ),
            ("files", ("image.png", _png_bytes(), "image/png")),
            ("files", ("voice.wav", b"RIFF....WAVEfmt ", "audio/wav")),
            ("files", ("clip.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")),
        ],
    )
    assert response.status_code == 201
    return response.json()["data"]


def test_parse_all_files_generates_multimodal_evidence_and_video_frame(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    _upload_mixed_files(client, headers, task_id)

    summary = parse_service.parse_all_files(task_id)

    assert summary.total_files == 6
    assert summary.parsed_files == 6
    with SessionLocal() as db:
        evidence = db.query(Evidence).filter(Evidence.task_id == task_id).order_by(Evidence.display_id).all()
        assert evidence[0].display_id == "E-0001"
        assert len({item.display_id for item in evidence}) == len(evidence)
        locators = [item.locator_json for item in evidence]
        assert any('"kind": "text"' in locator for locator in locators)
        assert any('"kind": "image"' in locator for locator in locators)
        assert any('"kind": "audio"' in locator for locator in locators)
        assert any('"kind": "video_audio"' in locator for locator in locators)
        assert any('"kind": "video_frame"' in locator for locator in locators)

    frame_dir = settings.data_root_path / "tasks" / task_id / "derived" / "frames"
    assert any(path.suffix == ".png" for path in frame_dir.iterdir())


def test_evidence_index_returns_all_display_ids_beyond_page_limit(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    [uploaded] = client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[("files", ("note.txt", b"ready", "text/plain"))],
    ).json()["data"]
    with SessionLocal() as db:
        for index in range(55):
            db.add(
                Evidence(
                    display_id=f"E-{index + 1:04d}",
                    task_id=task_id,
                    file_id=uploaded["id"],
                    modality="text",
                    evidence_type="paragraph",
                    content=f"evidence {index + 1}",
                    locator_json="{}",
                    skill_id="document_parse",
                )
            )
        db.commit()

    paged = client.get(
        f"/api/v1/tasks/{task_id}/evidence?page=1&page_size=500",
        headers=headers,
    )
    indexed = client.get(f"/api/v1/tasks/{task_id}/evidence/index", headers=headers)

    assert paged.status_code == 200
    assert len(paged.json()["data"]["items"]) == 50
    assert indexed.status_code == 200
    items = indexed.json()["data"]
    assert len(items) == 55
    item_51 = items[50]
    assert item_51["display_id"] == "E-0051"
    assert item_51["id"]
    assert item_51["modality"] == "text"
    assert item_51["evidence_type"] == "paragraph"


def test_disabled_parser_marks_matching_files_warning_and_skips_evidence(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    [uploaded] = client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[("files", ("image.png", _png_bytes(), "image/png"))],
    ).json()["data"]
    with SessionLocal() as db:
        config = db.get(SkillConfig, "image_ocr")
        config.enabled = False
        db.commit()

    summary = parse_service.parse_all_files(task_id)

    assert summary.warning_files == 1
    with SessionLocal() as db:
        file = db.get(TaskFile, uploaded["id"])
        assert file.status == "warning"
        assert file.error_message == "image_ocr disabled"
        assert db.query(Evidence).filter(Evidence.file_id == uploaded["id"]).count() == 0


def test_corrupt_document_marks_file_failed_without_blocking_other_files(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    response = client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[
            ("files", ("broken.pdf", b"%PDF-1.4\nbroken", "application/pdf")),
            ("files", ("note.txt", b"good text", "text/plain")),
        ],
    )
    assert response.status_code == 201

    summary = parse_service.parse_all_files(task_id)

    assert summary.failed_files == 1
    assert summary.parsed_files == 1
    with SessionLocal() as db:
        files = {file.original_name: file for file in db.query(TaskFile).filter(TaskFile.task_id == task_id)}
        assert files["broken.pdf"].status == "failed"
        assert files["note.txt"].status == "parsed"
        assert db.query(Evidence).filter(Evidence.file_id == files["note.txt"].id).count() == 1


def test_parse_error_details_are_redacted_in_db_summary_and_task_detail(client, create_user, monkeypatch):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    [uploaded] = client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[("files", ("note.txt", b"ready", "text/plain"))],
    ).json()["data"]
    sensitive_path = settings.data_root_path / "tasks" / task_id / "original" / uploaded["stored_name"]

    class FailingSkill:
        def run(self, _context, _payload):
            return SkillResult(
                success=False,
                errors=[f"task_id={task_id} file_id={uploaded['id']} failed reading {sensitive_path}"],
            )

    monkeypatch.setattr(parse_service, "get_skill", lambda _skill_id: FailingSkill())

    summary = parse_service.parse_all_files(task_id)

    assert summary.failed_files == 1
    assert str(settings.data_root_path) not in summary.errors[0]
    assert "[data-root]" in summary.errors[0]
    assert task_id in summary.errors[0]
    assert uploaded["id"] in summary.errors[0]
    with SessionLocal() as db:
        file = db.get(TaskFile, uploaded["id"])
        assert str(settings.data_root_path) not in file.error_message
        assert "[data-root]" in file.error_message

    detail = client.get(f"/api/v1/tasks/{task_id}", headers=headers).json()["data"]
    returned_error = detail["files"][0]["error_message"]
    assert str(settings.data_root_path) not in returned_error
    assert "[data-root]" in returned_error


def test_parse_endpoint_top_level_error_redacts_task_last_error(client, create_user, monkeypatch):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[("files", ("note.txt", b"ready", "text/plain"))],
    )
    sensitive_path = settings.data_root_path / "models" / "ocr"

    def fail_parse(_task_id: str):
        raise RuntimeError(f"task_id={task_id} cannot open {sensitive_path}")

    monkeypatch.setattr(parse_service, "parse_all_files", fail_parse)

    with pytest.raises(RuntimeError):
        parse_service.parse_task_files_for_endpoint(task_id)

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        assert task.status == "failed"
        assert str(settings.data_root_path) not in task.last_error
        assert "[data-root]" in task.last_error
        assert task_id in task.last_error

    detail = client.get(f"/api/v1/tasks/{task_id}", headers=headers).json()["data"]
    assert str(settings.data_root_path) not in detail["last_error"]
    assert "[data-root]" in detail["last_error"]


def test_parse_all_files_does_not_finalize_task_or_run_when_file_fails(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    response = client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[
            ("files", ("broken.pdf", b"%PDF-1.4\nbroken", "application/pdf")),
            ("files", ("note.txt", b"good text", "text/plain")),
        ],
    )
    assert response.status_code == 201
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        task.status = "extracting"
        run = TaskRun(task_id=task_id, status="running", progress=7, current_step="parsing")
        db.add(run)
        db.commit()
        run_id = run.id

    summary = parse_service.parse_all_files(task_id, run_id=run_id)

    assert summary.failed_files == 1
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        run = db.get(TaskRun, run_id)
        assert task.status == "extracting"
        assert run.status == "running"
        assert run.progress == 100
        assert run.error_message is None


def test_reparse_cleans_only_current_file_derived_artifacts(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    [video_file] = client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[("files", ("clip.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4"))],
    ).json()["data"]
    task_dir = settings.data_root_path / "tasks" / task_id
    frames_dir = task_dir / "derived" / "frames"
    audio_dir = task_dir / "derived" / "audio"
    frames_dir.mkdir(parents=True)
    audio_dir.mkdir(parents=True)
    old_frame = frames_dir / f"{video_file['id']}_frame_999999.png"
    other_frame = frames_dir / "unrelated_file_frame_999999.png"
    old_audio = audio_dir / f"{video_file['id']}.wav"
    other_audio = audio_dir / "unrelated_file.wav"
    for path in [old_frame, other_frame, old_audio, other_audio]:
        path.write_bytes(b"old")

    parse_service.parse_all_files(task_id)

    assert not old_frame.exists()
    assert not old_audio.exists()
    assert other_frame.exists()
    assert other_audio.exists()


def test_parse_endpoint_rejects_running_task(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    with SessionLocal() as db:
        task_file = TaskFile(
            task_id=task_id,
            original_name="note.txt",
            stored_name="note.txt",
            extension="txt",
            mime_type="text/plain",
            size_bytes=4,
            modality="text",
        )
        db.add(task_file)
        task = db.get(Task, task_id)
        task.status = "parsing"
        db.commit()

    response = client.post(f"/api/v1/tasks/{task_id}/parse", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TASK_ALREADY_RUNNING"


def test_parse_endpoint_rejects_when_another_task_is_running(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    running_task_id = _create_task(client, headers)
    waiting_task_id = _create_task(client, headers)
    client.post(
        f"/api/v1/tasks/{waiting_task_id}/files",
        headers=headers,
        files=[("files", ("note.txt", b"ready", "text/plain"))],
    )
    with SessionLocal() as db:
        db.get(Task, running_task_id).status = "detecting_conflicts"
        db.commit()

    response = client.post(f"/api/v1/tasks/{waiting_task_id}/parse", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TASK_ALREADY_RUNNING"


def test_parse_endpoint_rejects_when_any_task_run_is_running(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    running_task_id = _create_task(client, headers)
    waiting_task_id = _create_task(client, headers)
    client.post(
        f"/api/v1/tasks/{waiting_task_id}/files",
        headers=headers,
        files=[("files", ("note.txt", b"ready", "text/plain"))],
    )
    with SessionLocal() as db:
        db.add(TaskRun(task_id=running_task_id, status="running"))
        db.commit()

    response = client.post(f"/api/v1/tasks/{waiting_task_id}/parse", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TASK_ALREADY_RUNNING"


def test_evidence_apis_enforce_task_access_and_return_source_urls(client, create_user):
    create_user("owner")
    create_user("other")
    owner_headers = login_headers(client, "owner", "password")
    other_headers = login_headers(client, "other", "password")
    task_id = _create_task(client, owner_headers)
    [uploaded] = _upload_mixed_files(client, owner_headers, task_id)[:1]
    parse_service.parse_all_files(task_id)
    with SessionLocal() as db:
        evidence = db.query(Evidence).filter(Evidence.file_id == uploaded["id"]).first()

    list_response = client.get(f"/api/v1/tasks/{task_id}/evidence", headers=owner_headers)
    detail_response = client.get(f"/api/v1/evidence/{evidence.id}", headers=owner_headers)
    source_response = client.get(f"/api/v1/evidence/{evidence.id}/source", headers=owner_headers)
    forbidden_response = client.get(f"/api/v1/evidence/{evidence.id}", headers=other_headers)

    assert list_response.status_code == 200
    assert list_response.json()["data"]["total"] >= 1
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["display_id"] == evidence.display_id
    assert source_response.status_code == 200
    source = source_response.json()["data"]
    assert source["locator"]["kind"] == "text"
    assert source["file_url"] == f"/api/v1/files/{uploaded['id']}/stream"
    assert forbidden_response.status_code == 404
