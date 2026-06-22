import json
import shutil
import subprocess

import pytest

from app.config import settings
from app.models import Task, TaskFile
from app.services.task_service import serialize_file
from app.skills.audio_transcribe import AudioTranscribeSkill
from app.skills.base import SkillContext
from app.skills import audio_transcribe as audio_transcribe_module
from app.skills import image_ocr as image_ocr_module
from app.skills.image_ocr import ImageOcrSkill
from app.skills import visual_understand as visual_understand_module
from app.skills import video_parse as video_parse_module
from app.skills.video_parse import NO_FRAME_TEXT_WARNING, NO_VIDEO_AUDIO_WARNING, VideoParseSkill
from app.skills.visual_understand import VisualUnderstandSkill
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


def test_mock_image_visual_understand_reads_caption_sidecar():
    task_id = "image-caption-task"
    file = _insert_file(task_id, "image.png", "png", "image")
    fixture = settings.data_root_path / "tasks" / task_id / "original" / "image.png.caption.json"
    fixture.write_text(json.dumps({"caption": "画面显示检查站旁有三辆车。"}), encoding="utf-8")

    result = VisualUnderstandSkill().run(_context(task_id), {"file": serialize_file(file)})

    assert result.success is True
    evidence = result.data["evidence"]
    assert evidence == [
        {
            "content": "画面显示检查站旁有三辆车。",
            "modality": "image",
            "evidence_type": "image_caption",
            "locator": {"kind": "image"},
            "confidence": None,
        }
    ]


def test_mock_image_visual_understand_default_caption_when_fixture_missing():
    task_id = "image-caption-default-task"
    file = _insert_file(task_id, "image.png", "png", "image")

    result = VisualUnderstandSkill().run(_context(task_id), {"file": serialize_file(file)})

    assert result.success is True
    evidence = result.data["evidence"]
    assert evidence[0]["evidence_type"] == "image_caption"
    assert evidence[0]["locator"] == {"kind": "image"}
    assert "MOCK 画面描述" in evidence[0]["content"]
    assert "image.png" in evidence[0]["content"]


def test_real_image_visual_understand_uses_vlm_when_media_is_mocked(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_media", True)
    monkeypatch.setattr(settings, "mock_vision", None, raising=False)
    monkeypatch.setattr(settings, "vlm_base_url", "https://vlm.example/v1", raising=False)
    monkeypatch.setattr(settings, "vlm_api_key", "private-vlm-api-key", raising=False)
    monkeypatch.setattr(settings, "vlm_model", "qwen-vl", raising=False)
    task_id = "real-vlm-image-task"
    file = _insert_file(task_id, "image.png", "png", "image")

    class FakeVisionClient:
        def __init__(self) -> None:
            self.calls = []

        def describe_image(self, path, prompt):
            self.calls.append((path, prompt))
            return "真实 VLM 描述：画面中有车辆。"

    client = FakeVisionClient()
    result = VisualUnderstandSkill(vision_client=client).run(_context(task_id), {"file": serialize_file(file)})

    assert result.success is True
    assert result.warnings == []
    assert len(client.calls) == 1
    assert client.calls[0][0].name == "image.png"
    assert result.data["evidence"][0]["content"] == "真实 VLM 描述：画面中有车辆。"


def test_real_image_visual_understand_failure_warns_without_error(monkeypatch):
    monkeypatch.setattr(settings, "mock_vision", False, raising=False)
    monkeypatch.setattr(settings, "vlm_api_key", "private-vlm-api-key", raising=False)
    task_id = "failing-vlm-image-task"
    file = _insert_file(task_id, "image.png", "png", "image")

    class FailingVisionClient:
        def describe_image(self, _path, _prompt):
            raise RuntimeError(f"VLM 返回 HTTP 403: {settings.vlm_api_key}")

    result = VisualUnderstandSkill(vision_client=FailingVisionClient()).run(
        _context(task_id),
        {"file": serialize_file(file)},
    )

    assert result.success is True
    assert result.errors == []
    assert result.data["evidence"] == []
    assert len(result.warnings) == 1
    assert "视觉理解失败: RuntimeError: VLM 返回 HTTP 403" in result.warnings[0]
    assert "private-vlm-api-key" not in result.warnings[0]


def test_mock_image_ocr_empty_fixture_warns_without_fabricating_text():
    task_id = "empty-image-task"
    file = _insert_file(task_id, "image.png", "png", "image")
    fixture = settings.data_root_path / "tasks" / task_id / "original" / "image.png.ocr.json"
    fixture.write_text(json.dumps({"items": []}), encoding="utf-8")

    result = ImageOcrSkill().run(_context(task_id), {"file": serialize_file(file)})

    assert result.success is True
    assert result.data["evidence"] == []
    assert result.warnings == ["OCR 未识别到文本"]


def test_real_image_ocr_uses_http_service_when_base_url_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_media", False)
    monkeypatch.setattr(settings, "ocr_base_url", "http://ocr.local", raising=False)
    monkeypatch.setattr(settings, "ocr_model_dir", None, raising=False)
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"png")
    calls: list[str] = []

    def fake_ocr_image(base_url, path):
        calls.append(f"{base_url}|{path.name}")
        return [
            {"text": "  第一行  ", "score": 0.91, "box": [1, 2, 30, 40]},
            {"text": "   ", "score": 0.1, "box": [9, 9, 10, 10]},
        ]

    monkeypatch.setattr(image_ocr_module.media_client, "ocr_image", fake_ocr_image)

    evidence, warnings = image_ocr_module.real_ocr_evidence(image_path)

    assert calls == ["http://ocr.local|image.png"]
    assert warnings == []
    assert evidence == [
        {
            "content": "第一行",
            "modality": "image",
            "evidence_type": "ocr",
            "locator": {"kind": "image", "bbox": [1, 2, 30, 40]},
            "confidence": 0.91,
        }
    ]


def test_real_image_ocr_http_empty_results_warns(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_media", False)
    monkeypatch.setattr(settings, "ocr_base_url", "http://ocr.local", raising=False)
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"png")
    monkeypatch.setattr(image_ocr_module.media_client, "ocr_image", lambda *_args: [])

    evidence, warnings = image_ocr_module.real_ocr_evidence(image_path)

    assert evidence == []
    assert warnings == ["OCR 未识别到文本"]


def test_real_image_ocr_http_error_returns_skill_failure_without_file_path(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_media", False)
    monkeypatch.setattr(settings, "ocr_base_url", "http://ocr.local", raising=False)
    task_id = "http-ocr-failure-task"
    file = _insert_file(task_id, "private-image.png", "png", "image")

    def fail_ocr(_base_url, _path):
        raise RuntimeError("OCR 服务返回 HTTP 503")

    monkeypatch.setattr(image_ocr_module.media_client, "ocr_image", fail_ocr)

    result = ImageOcrSkill().run(_context(task_id), {"file": serialize_file(file)})

    assert result.success is False
    assert result.data["evidence"] == []
    assert "OCR 服务返回 HTTP 503" in result.errors[0]


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


def test_real_audio_transcribe_uses_http_service_when_base_url_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_media", False)
    monkeypatch.setattr(settings, "asr_base_url", "http://asr.local", raising=False)
    monkeypatch.setattr(settings, "asr_model_dir", None, raising=False)
    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"wav")
    calls: list[str] = []

    def fake_asr_audio(base_url, path):
        calls.append(f"{base_url}|{path.name}")
        return {
            "duration": 3.0,
            "segments": [
                {"start": 0.125, "end": 1.5, "speaker": "说话人1", "text": "  目标出现  "},
                {"start": 2.0, "end": 2.5, "speaker": None, "text": "   "},
            ],
        }

    monkeypatch.setattr(audio_transcribe_module.media_client, "asr_audio", fake_asr_audio)

    evidence, warnings = audio_transcribe_module.real_transcript_evidence(audio_path)

    assert calls == ["http://asr.local|voice.wav"]
    assert warnings == []
    assert evidence == [
        {
            "content": "[说话人1] 目标出现",
            "modality": "audio",
            "evidence_type": "asr",
            "locator": {"kind": "audio", "start_ms": 125, "end_ms": 1500},
            "confidence": None,
        }
    ]


def test_real_audio_transcribe_http_empty_segments_warns(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_media", False)
    monkeypatch.setattr(settings, "asr_base_url", "http://asr.local", raising=False)
    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"wav")
    monkeypatch.setattr(
        audio_transcribe_module.media_client,
        "asr_audio",
        lambda *_args: {"duration": 0.0, "segments": []},
    )

    evidence, warnings = audio_transcribe_module.real_transcript_evidence(audio_path)

    assert evidence == []
    assert warnings == ["ASR 未识别到语音文本"]


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
    assert result.data["frames"] == [
        {
            "timestamp_ms": 1000,
            "frame_path": frame_path,
        }
    ]


def test_mock_video_visual_understand_reads_frame_caption_sidecar():
    task_id = "video-caption-task"
    file = _insert_file(task_id, "clip.mp4", "mp4", "video")
    frames_dir = settings.data_root_path / "tasks" / task_id / "derived" / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_path = frames_dir / "clip_frame_000001.png"
    frame_path.write_bytes(b"png")
    fixture = settings.data_root_path / "tasks" / task_id / "original" / "clip.mp4.caption.json"
    fixture.write_text(
        json.dumps({"frames": [{"timestamp_ms": 2000, "caption": "关键帧显示仓库入口和车辆。"}]}),
        encoding="utf-8",
    )

    result = VisualUnderstandSkill().run(
        _context(task_id),
        {
            "file": serialize_file(file),
            "frames": [{"timestamp_ms": 2000, "frame_path": "derived/frames/clip_frame_000001.png"}],
        },
    )

    assert result.success is True
    assert result.data["evidence"] == [
        {
            "content": "关键帧显示仓库入口和车辆。",
            "modality": "video",
            "evidence_type": "video_frame_caption",
            "locator": {
                "kind": "video_frame",
                "timestamp_ms": 2000,
                "frame_path": "derived/frames/clip_frame_000001.png",
            },
            "confidence": None,
        }
    ]


def test_real_video_visual_understand_extracts_original_frames_when_media_is_mocked(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_media", True)
    monkeypatch.setattr(settings, "mock_vision", None, raising=False)
    monkeypatch.setattr(settings, "vlm_base_url", "https://vlm.example/v1", raising=False)
    monkeypatch.setattr(settings, "vlm_api_key", "private-vlm-api-key", raising=False)
    monkeypatch.setattr(settings, "vlm_model", "qwen-vl", raising=False)
    task_id = "real-vlm-video-task"
    file = _insert_file(task_id, "clip.mp4", "mp4", "video")
    context = _context(task_id)
    real_frame_path = f"derived/frames/{file.id}_frame_000001.png"
    (settings.data_root_path / "tasks" / task_id / real_frame_path).parent.mkdir(parents=True, exist_ok=True)
    (settings.data_root_path / "tasks" / task_id / real_frame_path).write_bytes(b"png")
    extracted: list[str] = []

    def fake_extract_video_frames(_context, file_info):
        extracted.append(file_info["id"])
        return [{"timestamp_ms": 0, "frame_path": real_frame_path}]

    monkeypatch.setattr(visual_understand_module, "extract_video_frames", fake_extract_video_frames, raising=False)

    class FakeVisionClient:
        def __init__(self) -> None:
            self.paths = []

        def describe_image(self, path, _prompt):
            self.paths.append(path)
            return "真实视频帧描述"

    client = FakeVisionClient()
    result = VisualUnderstandSkill(vision_client=client).run(
        context,
        {
            "file": serialize_file(file),
            "frames": [{"timestamp_ms": 1000, "frame_path": "derived/frames/mock_frame.png"}],
        },
    )

    assert result.success is True
    assert extracted == [file.id]
    assert [path.name for path in client.paths] == [f"{file.id}_frame_000001.png"]
    assert result.data["evidence"] == [
        {
            "content": "真实视频帧描述",
            "modality": "video",
            "evidence_type": "video_frame_caption",
            "locator": {
                "kind": "video_frame",
                "timestamp_ms": 0,
                "frame_path": real_frame_path,
            },
            "confidence": None,
        }
    ]


def test_real_video_visual_understand_reuses_video_parse_frames_when_media_is_real(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_media", False)
    monkeypatch.setattr(settings, "mock_vision", None, raising=False)
    monkeypatch.setattr(settings, "vlm_base_url", "https://vlm.example/v1", raising=False)
    monkeypatch.setattr(settings, "vlm_api_key", "private-vlm-api-key", raising=False)
    monkeypatch.setattr(settings, "vlm_model", "qwen-vl", raising=False)
    task_id = "real-vlm-video-reuse-frames-task"
    file = _insert_file(task_id, "clip.mp4", "mp4", "video")
    context = _context(task_id)
    parsed_frame_path = "derived/frames/video_parse_frame_000001.png"
    (settings.data_root_path / "tasks" / task_id / parsed_frame_path).parent.mkdir(parents=True, exist_ok=True)
    (settings.data_root_path / "tasks" / task_id / parsed_frame_path).write_bytes(b"png")
    extracted: list[str] = []

    def fake_extract_video_frames(_context, file_info):
        extracted.append(file_info["id"])
        extracted_frame_path = "derived/frames/extracted_again_frame_000001.png"
        (settings.data_root_path / "tasks" / task_id / extracted_frame_path).write_bytes(b"png")
        return [{"timestamp_ms": 0, "frame_path": extracted_frame_path}]

    monkeypatch.setattr(visual_understand_module, "extract_video_frames", fake_extract_video_frames, raising=False)

    class FakeVisionClient:
        def __init__(self) -> None:
            self.paths = []

        def describe_image(self, path, _prompt):
            self.paths.append(path)
            return "复用视频帧描述"

    client = FakeVisionClient()
    result = VisualUnderstandSkill(vision_client=client).run(
        context,
        {
            "file": serialize_file(file),
            "frames": [{"timestamp_ms": 1000, "frame_path": parsed_frame_path}],
        },
    )

    assert result.success is True
    assert result.warnings == []
    assert extracted == []
    assert [path.name for path in client.paths] == ["video_parse_frame_000001.png"]
    assert result.data["evidence"] == [
        {
            "content": "复用视频帧描述",
            "modality": "video",
            "evidence_type": "video_frame_caption",
            "locator": {
                "kind": "video_frame",
                "timestamp_ms": 1000,
                "frame_path": parsed_frame_path,
            },
            "confidence": None,
        }
    ]


def test_real_video_visual_understand_ffmpeg_failure_warns_and_skips(monkeypatch):
    monkeypatch.setattr(settings, "mock_vision", False, raising=False)
    task_id = "ffmpeg-failing-vlm-video-task"
    file = _insert_file(task_id, "clip.mp4", "mp4", "video")

    def fake_extract_video_frames(_context, _file_info):
        raise RuntimeError("FFmpeg 不可用，无法抽取视频关键帧")

    monkeypatch.setattr(visual_understand_module, "extract_video_frames", fake_extract_video_frames, raising=False)

    class UnexpectedVisionClient:
        def describe_image(self, _path, _prompt):
            pytest.fail("VLM should not run when frame extraction fails")

    result = VisualUnderstandSkill(vision_client=UnexpectedVisionClient()).run(
        _context(task_id),
        {"file": serialize_file(file)},
    )

    assert result.success is True
    assert result.errors == []
    assert result.data["evidence"] == []
    assert result.warnings == ["视频视觉理解跳过: RuntimeError: FFmpeg 不可用，无法抽取视频关键帧"]


def test_mock_video_parse_empty_frame_fixture_warns_without_fabricating_text():
    task_id = "empty-video-frame-task"
    file = _insert_file(task_id, "clip.mp4", "mp4", "video")
    fixture = settings.data_root_path / "tasks" / task_id / "original" / "clip.mp4.video.json"
    fixture.write_text(json.dumps({"audio_segments": [], "frames": []}), encoding="utf-8")

    result = VideoParseSkill().run(_context(task_id), {"file": serialize_file(file)})

    assert result.success is True
    assert result.data["evidence"] == []
    assert result.warnings == [NO_VIDEO_AUDIO_WARNING, NO_FRAME_TEXT_WARNING]


def test_mock_video_parse_no_audio_fixture_still_generates_frame_evidence():
    task_id = "no-audio-video-task"
    file = _insert_file(task_id, "clip.mp4", "mp4", "video")
    fixture = settings.data_root_path / "tasks" / task_id / "original" / "clip.mp4.video.json"
    fixture.write_text(
        json.dumps(
            {
                "audio_segments": [],
                "frames": [{"text": "fixture frame text", "timestamp_ms": 1000}],
            }
        ),
        encoding="utf-8",
    )

    result = VideoParseSkill().run(_context(task_id), {"file": serialize_file(file)})

    assert result.success is True
    assert result.warnings == [NO_VIDEO_AUDIO_WARNING]
    assert [item["locator"]["kind"] for item in result.data["evidence"]] == ["video_frame"]
    assert result.data["evidence"][0]["content"] == "fixture frame text"


def test_real_video_parse_continues_frame_ocr_when_audio_extraction_fails(monkeypatch):
    task_id = "real-video-no-audio-task"
    file = _insert_file(task_id, "clip.mp4", "mp4", "video")
    context = _context(task_id)

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        video_parse_module,
        "real_transcript_evidence",
        lambda *args, **kwargs: pytest.fail("audio transcription should not run when audio extraction fails"),
    )
    monkeypatch.setattr(
        video_parse_module,
        "real_ocr_evidence",
        lambda path: (
            [
                {
                    "content": "frame text",
                    "locator": {"bbox": [1, 2, 3, 4]},
                    "confidence": 0.8,
                }
            ],
            [],
        ),
    )

    calls: list[list[str]] = []

    def fake_run_ffmpeg(command: list[str], *, timeout: int) -> None:
        calls.append(command)
        if "-vn" in command:
            raise RuntimeError("no audio stream")
        frames_dir = settings.data_root_path / "tasks" / task_id / "derived" / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        (frames_dir / f"{file.id}_frame_000001.png").write_bytes(b"png")

    monkeypatch.setattr(video_parse_module, "_run_ffmpeg", fake_run_ffmpeg)

    evidence, warnings = video_parse_module.real_video_evidence(context, serialize_file(file))

    assert len(calls) == 2
    assert warnings == [NO_VIDEO_AUDIO_WARNING]
    assert [item["locator"]["kind"] for item in evidence] == ["video_frame"]
    assert evidence[0]["content"] == "frame text"


def test_real_video_parse_wraps_http_ocr_and_asr_outputs(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_media", False)
    monkeypatch.setattr(settings, "ocr_base_url", "http://ocr.local", raising=False)
    monkeypatch.setattr(settings, "asr_base_url", "http://asr.local", raising=False)
    task_id = "real-video-http-media-task"
    file = _insert_file(task_id, "clip.mp4", "mp4", "video")
    context = _context(task_id)
    frame_path = f"derived/frames/{file.id}_frame_000001.png"
    absolute_frame = settings.data_root_path / "tasks" / task_id / frame_path
    absolute_frame.parent.mkdir(parents=True, exist_ok=True)
    absolute_frame.write_bytes(b"png")

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/ffmpeg")

    def fake_run_ffmpeg(command: list[str], *, timeout: int) -> None:
        if "-vn" in command:
            with open(command[-1], "wb") as handle:
                handle.write(b"wav")

    def fake_extract_video_frames(_context, _file_info):
        return [{"timestamp_ms": 7000, "frame_path": frame_path}]

    monkeypatch.setattr(video_parse_module, "_run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr(video_parse_module, "extract_video_frames", fake_extract_video_frames)
    monkeypatch.setattr(
        audio_transcribe_module.media_client,
        "asr_audio",
        lambda _base_url, _path: {
            "duration": 2.0,
            "segments": [{"start": 0.5, "end": 1.75, "speaker": "说话人2", "text": "音轨文字"}],
        },
    )
    monkeypatch.setattr(
        image_ocr_module.media_client,
        "ocr_image",
        lambda _base_url, _path: [{"text": "帧文字", "score": 0.82, "box": [4, 5, 60, 70]}],
    )

    evidence, warnings, frames = video_parse_module.real_video_outputs(context, serialize_file(file))

    assert warnings == []
    assert frames == [{"timestamp_ms": 7000, "frame_path": frame_path}]
    assert evidence == [
        {
            "content": "[说话人2] 音轨文字",
            "modality": "video",
            "evidence_type": "asr",
            "locator": {"kind": "video_audio", "start_ms": 500, "end_ms": 1750},
            "confidence": None,
        },
        {
            "content": "帧文字",
            "modality": "video",
            "evidence_type": "video_frame_ocr",
            "locator": {
                "kind": "video_frame",
                "timestamp_ms": 7000,
                "frame_path": frame_path,
                "bbox": [4, 5, 60, 70],
            },
            "confidence": 0.82,
        },
    ]


def test_real_video_parse_warns_and_keeps_frame_evidence_when_asr_and_one_ocr_frame_fail(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_media", False)
    task_id = "real-video-http-media-failure-task"
    file = _insert_file(task_id, "clip.mp4", "mp4", "video")
    context = _context(task_id)
    first_frame = f"derived/frames/{file.id}_frame_000001.png"
    second_frame = f"derived/frames/{file.id}_frame_000002.png"
    for frame_path in (first_frame, second_frame):
        absolute_frame = settings.data_root_path / "tasks" / task_id / frame_path
        absolute_frame.parent.mkdir(parents=True, exist_ok=True)
        absolute_frame.write_bytes(b"png")

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(video_parse_module, "_run_ffmpeg", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        video_parse_module,
        "extract_video_frames",
        lambda _context, _file_info: [
            {"timestamp_ms": 1000, "frame_path": first_frame},
            {"timestamp_ms": 2000, "frame_path": second_frame},
        ],
    )
    monkeypatch.setattr(
        video_parse_module,
        "real_transcript_evidence",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("ASR HTTP service returned HTTP 503")),
    )

    def fake_ocr(path):
        if path.name.endswith("000001.png"):
            raise RuntimeError("OCR HTTP service returned non-JSON response")
        return (
            [
                {
                    "content": "second frame text",
                    "locator": {"bbox": [1, 2, 3, 4]},
                    "confidence": 0.7,
                }
            ],
            [],
        )

    monkeypatch.setattr(video_parse_module, "real_ocr_evidence", fake_ocr)

    evidence, warnings, frames = video_parse_module.real_video_outputs(context, serialize_file(file))

    assert frames == [
        {"timestamp_ms": 1000, "frame_path": first_frame},
        {"timestamp_ms": 2000, "frame_path": second_frame},
    ]
    assert warnings == [NO_VIDEO_AUDIO_WARNING, NO_FRAME_TEXT_WARNING]
    assert [item["content"] for item in evidence] == ["second frame text"]
    assert evidence[0]["locator"]["frame_path"] == second_frame


def test_extract_video_frames_uses_ffmpeg_interval_and_safe_relative_paths(monkeypatch):
    task_id = "extract-video-frames-task"
    file = _insert_file(task_id, "clip.mp4", "mp4", "video")
    context = _context(task_id)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(settings, "video_frame_interval_sec", 7)
    calls: list[list[str]] = []

    def fake_run_ffmpeg(command: list[str], *, timeout: int) -> None:
        calls.append(command)
        output_pattern = command[-1]
        frame_path = output_pattern.replace("%06d", "000001")
        with open(frame_path, "wb") as handle:
            handle.write(b"png")

    monkeypatch.setattr(video_parse_module, "_run_ffmpeg", fake_run_ffmpeg)

    frames = video_parse_module.extract_video_frames(context, serialize_file(file))

    assert len(calls) == 1
    assert calls[0][calls[0].index("-vf") + 1] == "fps=1/7"
    assert frames == [{"timestamp_ms": 0, "frame_path": f"derived/frames/{file.id}_frame_000001.png"}]
    absolute_frame = settings.data_root_path / "tasks" / task_id / frames[0]["frame_path"]
    assert absolute_frame.is_file()


def test_run_ffmpeg_converts_timeout_to_runtime_error(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="ffmpeg timed out after 120s"):
        video_parse_module._run_ffmpeg(["ffmpeg", "-version"], timeout=120)


def test_invalid_sidecar_fixture_is_ignored_with_warning():
    task_id = "bad-fixture-image-task"
    file = _insert_file(task_id, "image.png", "png", "image")
    fixture = settings.data_root_path / "tasks" / task_id / "original" / "image.png.ocr.json"
    fixture.write_text("{not json", encoding="utf-8")

    with pytest.warns(RuntimeWarning, match="Invalid mock fixture ignored"):
        result = ImageOcrSkill().run(_context(task_id), {"file": serialize_file(file)})

    assert result.success is True
    assert len(result.data["evidence"]) == 1
    assert result.data["evidence"][0]["content"] == "MOCK OCR 文本"


def test_media_mock_override_uses_fixture_when_llm_is_real(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "mock_media", True)
    task_id = "split-mock-image-task"
    file = _insert_file(task_id, "image.png", "png", "image")

    result = ImageOcrSkill().run(_context(task_id), {"file": serialize_file(file)})

    assert result.success is True
    assert result.data["evidence"][0]["content"] == "MOCK OCR 文本"
