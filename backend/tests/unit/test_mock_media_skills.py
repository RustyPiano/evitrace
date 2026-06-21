import json

from app.config import settings
from app.models import Task, TaskFile
from app.services.task_service import serialize_file
from app.skills.audio_transcribe import AudioTranscribeSkill
from app.skills.base import SkillContext
from app.skills.image_ocr import ImageOcrSkill
from app.skills.video_parse import VideoParseSkill
from app.database import SessionLocal


def _insert_file(task_id: str, filename: str, extension: str, modality: str) -> TaskFile:
    original_dir = settings.data_root_path / "tasks" / task_id / "original"
    original_dir.mkdir(parents=True, exist_ok=True)
    path = original_dir / filename
    path.write_bytes(b"fixture")
    with SessionLocal() as db:
        task = Task(name="Media", objective="Objective", owner_id="owner", status="ready")
        task.id = task_id
        db.add(task)
        file = TaskFile(
            task_id=task_id,
            original_name=filename,
            stored_name=filename,
            extension=extension,
            mime_type=None,
            size_bytes=path.stat().st_size,
            modality=modality,
        )
        db.add(file)
        db.commit()
        db.refresh(file)
        return file


def _context(task_id: str) -> SkillContext:
    return SkillContext(task_id=task_id, run_id=None, data_root=str(settings.data_root_path))


def test_mock_image_ocr_default_fixture_generates_bbox_evidence():
    task_id = "image-task"
    file = _insert_file(task_id, "image.png", "png", "image")

    result = ImageOcrSkill().run(_context(task_id), {"file": serialize_file(file)})

    assert result.success is True
    evidence = result.data["evidence"]
    assert len(evidence) >= 1
    assert evidence[0]["evidence_type"] == "ocr"
    assert evidence[0]["locator"]["kind"] == "image"
    assert len(evidence[0]["locator"]["bbox"]) == 4


def test_mock_image_ocr_empty_fixture_warns_without_fabricating_text():
    task_id = "empty-image-task"
    file = _insert_file(task_id, "image.png", "png", "image")
    fixture = settings.data_root_path / "tasks" / task_id / "original" / "image.png.ocr.json"
    fixture.write_text(json.dumps({"items": []}), encoding="utf-8")

    result = ImageOcrSkill().run(_context(task_id), {"file": serialize_file(file)})

    assert result.success is True
    assert result.data["evidence"] == []
    assert result.warnings == ["OCR 未识别到文本"]


def test_mock_audio_transcribe_returns_segments_with_time_locators():
    task_id = "audio-task"
    file = _insert_file(task_id, "voice.wav", "wav", "audio")

    result = AudioTranscribeSkill().run(_context(task_id), {"file": serialize_file(file)})

    assert result.success is True
    evidence = result.data["evidence"]
    assert len(evidence) == 2
    assert evidence[0]["evidence_type"] == "asr"
    assert evidence[0]["locator"] == {"kind": "audio", "start_ms": 0, "end_ms": 2500}
    assert evidence[1]["locator"]["start_ms"] == 2500


def test_mock_audio_transcribe_empty_fixture_warns():
    task_id = "empty-audio-task"
    file = _insert_file(task_id, "voice.wav", "wav", "audio")
    fixture = settings.data_root_path / "tasks" / task_id / "original" / "voice.wav.asr.json"
    fixture.write_text(json.dumps({"segments": []}), encoding="utf-8")

    result = AudioTranscribeSkill().run(_context(task_id), {"file": serialize_file(file)})

    assert result.success is True
    assert result.data["evidence"] == []
    assert result.warnings == ["ASR 未识别到语音文本"]


def test_mock_video_parse_generates_audio_and_frame_evidence_with_safe_frame_path():
    task_id = "video-task"
    file = _insert_file(task_id, "clip.mp4", "mp4", "video")

    result = VideoParseSkill().run(_context(task_id), {"file": serialize_file(file)})

    assert result.success is True
    evidence = result.data["evidence"]
    kinds = {item["locator"]["kind"] for item in evidence}
    assert {"video_audio", "video_frame"} <= kinds
    frame_item = next(item for item in evidence if item["locator"]["kind"] == "video_frame")
    frame_path = frame_item["locator"]["frame_path"]
    assert frame_path.startswith("derived/frames/")
    absolute_frame = (settings.data_root_path / "tasks" / task_id / frame_path).resolve()
    task_dir = (settings.data_root_path / "tasks" / task_id).resolve()
    assert absolute_frame.is_file()
    assert absolute_frame.is_relative_to(task_dir)
