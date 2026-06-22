from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from app.config import settings
from app.database import SessionLocal
from app.models import Evidence, Task, TaskFile

from tests.conftest import login_headers


def test_public_config_exposes_upload_limit_without_sensitive_settings(client):
    response = client.get("/api/v1/config")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data == {"max_upload_mb": settings.max_upload_mb}
    assert "secret" not in response.text.lower()
    assert "api_key" not in response.text.lower()
    assert "database" not in response.text.lower()


def _create_task(client, headers) -> str:
    response = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"name": "Case A", "objective": "Verify files"},
    )
    assert response.status_code == 201
    return response.json()["data"]["id"]


def _docx_bytes() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types></Types>")
        archive.writestr("word/document.xml", "<w:document />")
    return buffer.getvalue()


def _add_evidence(task_id: str, file_id: str) -> None:
    with SessionLocal() as db:
        db.add(
            Evidence(
                display_id="E-0001",
                task_id=task_id,
                file_id=file_id,
                modality="text",
                evidence_type="paragraph",
                content="evidence",
                locator_json="{}",
                skill_id="document_parse",
            )
        )
        db.commit()


def test_supported_file_types_upload_successfully(client, create_user):
    create_user("analyst")
    headers = login_headers(client, "analyst", "password")
    task_id = _create_task(client, headers)

    files = [
        ("files", ("note.txt", b"hello", "text/plain")),
        ("files", ("report.pdf", b"%PDF-1.4\n", "application/pdf")),
        ("files", ("image.png", b"\x89PNG\r\n\x1a\n", "image/png")),
        ("files", ("image.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")),
        ("files", ("voice.wav", b"RIFF....WAVEfmt ", "audio/wav")),
        ("files", ("clip.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")),
        (
            "files",
            (
                "report.docx",
                _docx_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        ),
    ]

    response = client.post(f"/api/v1/tasks/{task_id}/files", headers=headers, files=files)

    assert response.status_code == 201
    uploaded = response.json()["data"]
    assert [file["extension"] for file in uploaded] == [
        "txt",
        "pdf",
        "png",
        "jpg",
        "wav",
        "mp4",
        "docx",
    ]
    assert [file["status"] for file in uploaded] == ["uploaded"] * 7

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        assert task.status == "ready"


def test_executable_file_is_rejected(client, create_user):
    create_user("analyst")
    headers = login_headers(client, "analyst", "password")
    task_id = _create_task(client, headers)

    response = client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[("files", ("tool.exe", b"MZ", "application/x-msdownload"))],
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "FILE_TYPE_NOT_SUPPORTED"


def test_shell_file_is_rejected(client, create_user):
    create_user("analyst")
    headers = login_headers(client, "analyst", "password")
    task_id = _create_task(client, headers)

    response = client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[("files", ("run.sh", b"#!/bin/sh", "text/x-shellscript"))],
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "FILE_TYPE_NOT_SUPPORTED"


def test_octet_stream_pdf_extension_with_executable_content_is_rejected(client, create_user):
    create_user("analyst")
    headers = login_headers(client, "analyst", "password")
    task_id = _create_task(client, headers)

    response = client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[("files", ("renamed.pdf", b"MZ executable", "application/octet-stream"))],
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "FILE_TYPE_NOT_SUPPORTED"


def test_oversized_file_is_rejected(client, create_user, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    create_user("analyst")
    headers = login_headers(client, "analyst", "password")
    task_id = _create_task(client, headers)

    response = client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[("files", ("big.txt", b"x", "text/plain"))],
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "FILE_TOO_LARGE"
    original_dir = settings.data_root_path / "tasks" / task_id / "original"
    assert not original_dir.exists() or list(original_dir.iterdir()) == []


def test_traversal_filename_is_sanitized_and_stays_in_task_directory(client, create_user):
    create_user("analyst")
    headers = login_headers(client, "analyst", "password")
    task_id = _create_task(client, headers)

    response = client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[("files", ("../../x.txt", b"safe", "text/plain"))],
    )

    assert response.status_code == 201
    uploaded = response.json()["data"][0]
    assert uploaded["original_name"] == "x.txt"
    task_dir = (settings.data_root_path / "tasks" / task_id).resolve()
    stored_path = (task_dir / "original" / uploaded["stored_name"]).resolve()
    assert stored_path.is_file()
    assert stored_path.is_relative_to(task_dir)
    assert not (settings.data_root_path / "x.txt").exists()


def test_user_without_task_access_cannot_download_file(client, create_user):
    create_user("owner")
    create_user("other")
    owner_headers = login_headers(client, "owner", "password")
    other_headers = login_headers(client, "other", "password")
    task_id = _create_task(client, owner_headers)
    upload_response = client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=owner_headers,
        files=[("files", ("note.txt", b"secret", "text/plain"))],
    )
    file_id = upload_response.json()["data"][0]["id"]

    response = client.get(f"/api/v1/files/{file_id}/stream", headers=other_headers)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "TASK_NOT_FOUND"


def test_malformed_range_header_returns_416(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    upload_response = client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[("files", ("note.txt", b"secret", "text/plain"))],
    )
    file_id = upload_response.json()["data"][0]["id"]

    response = client.get(
        f"/api/v1/files/{file_id}/stream",
        headers={**headers, "Range": "bytes=abc-def"},
    )

    assert response.status_code == 416
    assert response.json()["detail"]["code"] == "INVALID_RANGE"


def test_deleting_analyzed_task_file_is_rejected_and_evidence_remains(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    upload_response = client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[("files", ("note.txt", b"secret", "text/plain"))],
    )
    file_id = upload_response.json()["data"][0]["id"]
    _add_evidence(task_id, file_id)
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        task.status = "awaiting_review"
        db.commit()

    response = client.delete(f"/api/v1/files/{file_id}", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "FILE_DELETE_NOT_ALLOWED"
    with SessionLocal() as db:
        assert db.get(TaskFile, file_id) is not None
        assert db.query(Evidence).filter(Evidence.file_id == file_id).count() == 1


def test_deleting_ready_task_file_removes_associated_evidence(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    upload_response = client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[("files", ("note.txt", b"secret", "text/plain"))],
    )
    file_id = upload_response.json()["data"][0]["id"]
    _add_evidence(task_id, file_id)

    response = client.delete(f"/api/v1/files/{file_id}", headers=headers)

    assert response.status_code == 200
    with SessionLocal() as db:
        assert db.get(TaskFile, file_id) is None
        assert db.query(Evidence).filter(Evidence.file_id == file_id).count() == 0


def test_deleting_task_removes_task_directory(client, create_user):
    create_user("owner")
    headers = login_headers(client, "owner", "password")
    task_id = _create_task(client, headers)
    client.post(
        f"/api/v1/tasks/{task_id}/files",
        headers=headers,
        files=[("files", ("note.txt", b"secret", "text/plain"))],
    )
    task_dir = settings.data_root_path / "tasks" / task_id
    assert task_dir.is_dir()

    response = client.delete(f"/api/v1/tasks/{task_id}", headers=headers)

    assert response.status_code == 200
    assert not task_dir.exists()
    with SessionLocal() as db:
        assert db.query(TaskFile).filter(TaskFile.task_id == task_id).count() == 0
