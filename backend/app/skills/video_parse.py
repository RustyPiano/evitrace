from pathlib import Path
from time import perf_counter
from typing import Any

from app.config import settings

from .audio_transcribe import mock_transcript_evidence, real_transcript_evidence
from .base import SkillContext, SkillManifest, SkillResult
from .image_ocr import real_ocr_evidence
from .utils import coerce_items, derived_path, ensure_derived_dir, original_file_path, sidecar_fixture

NO_VIDEO_AUDIO_WARNING = "视频音轨未识别到语音文本"
NO_FRAME_TEXT_WARNING = "视频关键帧 OCR 未识别到文本"


class FfmpegTimeoutError(RuntimeError):
    pass


def _write_placeholder_frame(context: SkillContext, file_info: dict[str, Any], index: int) -> str:
    frames_dir = ensure_derived_dir(context, "frames")
    filename = f"{file_info['id']}_mock_frame_{index:06d}.png"
    path = (frames_dir / filename).resolve()
    if not path.is_relative_to(derived_path(context, "derived/frames")):
        raise ValueError("frame path escaped derived/frames")

    from PIL import Image, ImageDraw

    image = Image.new("RGB", (640, 360), color=(24, 38, 57))
    draw = ImageDraw.Draw(image)
    draw.rectangle((24, 24, 616, 336), outline=(96, 165, 250), width=3)
    draw.text((42, 42), "EviTrace MOCK FRAME", fill=(255, 255, 255))
    draw.text((42, 78), file_info["original_name"], fill=(203, 213, 225))
    image.save(path, format="PNG")
    return f"derived/frames/{filename}"


def _frame_evidence(item: dict[str, Any], frame_path: str) -> dict | None:
    text = str(item.get("text") or item.get("content") or "").strip()
    if not text:
        return None
    bbox = item.get("bbox") or [20, 20, 240, 80]
    return {
        "content": text,
        "modality": "video",
        "evidence_type": "video_frame_ocr",
        "locator": {
            "kind": "video_frame",
            "timestamp_ms": int(item.get("timestamp_ms", 0)),
            "frame_path": frame_path,
            "bbox": [int(value) for value in bbox],
        },
        "confidence": item.get("confidence"),
    }


def _default_frame_items() -> list[dict[str, Any]]:
    return [
        {
            "text": "MOCK 视频关键帧文字",
            "timestamp_ms": 1000,
            "bbox": [20, 20, 240, 80],
            "confidence": 0.88,
        }
    ]


def mock_video_evidence(context: SkillContext, file_info: dict[str, Any]) -> tuple[list[dict], list[str]]:
    fixture = sidecar_fixture(context, file_info, "video")
    audio_evidence, audio_warnings = mock_transcript_evidence(
        context,
        file_info,
        modality="video",
        locator_kind="video_audio",
    )
    if fixture is not None:
        raw_audio = coerce_items(fixture, ("audio_segments", "segments", "audio"))
        audio_evidence = []
        for raw in raw_audio:
            if isinstance(raw, dict):
                text = str(raw.get("text") or raw.get("content") or "").strip()
                if text:
                    audio_evidence.append(
                        {
                            "content": text,
                            "modality": "video",
                            "evidence_type": "asr",
                            "locator": {
                                "kind": "video_audio",
                                "start_ms": int(raw.get("start_ms", 0)),
                                "end_ms": int(raw.get("end_ms", 0)),
                            },
                            "confidence": raw.get("confidence"),
                        }
                    )
        audio_warnings = [] if audio_evidence else [NO_VIDEO_AUDIO_WARNING]

    if fixture is None:
        raw_frames = _default_frame_items()
    else:
        raw_frames = coerce_items(fixture, ("frame_ocr", "frames", "items"))

    frame_evidence: list[dict] = []
    for index, raw in enumerate(raw_frames):
        if not isinstance(raw, dict):
            continue
        frame_path = _write_placeholder_frame(context, file_info, index)
        item = _frame_evidence(raw, frame_path)
        if item is not None:
            frame_evidence.append(item)

    warnings = audio_warnings + ([] if frame_evidence else [NO_FRAME_TEXT_WARNING])
    return audio_evidence + frame_evidence, warnings


def _run_ffmpeg(command: list[str], *, timeout: int) -> None:
    import subprocess

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise FfmpegTimeoutError(f"ffmpeg timed out after {timeout}s") from exc
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "ffmpeg failed")


def real_video_evidence(context: SkillContext, file_info: dict[str, Any]) -> tuple[list[dict], list[str]]:
    import shutil

    if shutil.which("ffmpeg") is None:
        raise RuntimeError("FFmpeg 不可用，无法解析视频")

    source = original_file_path(context, file_info)
    audio_dir = ensure_derived_dir(context, "audio")
    frames_dir = ensure_derived_dir(context, "frames")
    audio_path = audio_dir / f"{file_info['id']}.wav"
    evidence: list[dict] = []
    warnings: list[str] = []
    try:
        _run_ffmpeg(
            ["ffmpeg", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", str(audio_path)],
            timeout=settings.ffmpeg_timeout_sec,
        )
    except FfmpegTimeoutError:
        raise
    except RuntimeError:
        warnings.append(NO_VIDEO_AUDIO_WARNING)
    else:
        evidence, audio_warnings = real_transcript_evidence(
            audio_path,
            modality="video",
            locator_kind="video_audio",
        )
        if audio_warnings:
            warnings.append(NO_VIDEO_AUDIO_WARNING)

    frame_pattern = frames_dir / f"{file_info['id']}_frame_%06d.png"
    interval = max(settings.video_frame_interval_sec, 1)
    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-vf",
            f"fps=1/{interval}",
            str(frame_pattern),
        ],
        timeout=settings.ffmpeg_timeout_sec,
    )

    frame_evidence: list[dict] = []
    for index, frame in enumerate(sorted(frames_dir.glob(f"{file_info['id']}_frame_*.png"))):
        ocr_items, _ = real_ocr_evidence(frame)
        relative_path = frame.relative_to(derived_path(context, ""))
        timestamp_ms = index * interval * 1000
        for ocr_item in ocr_items:
            locator = ocr_item["locator"]
            frame_evidence.append(
                {
                    "content": ocr_item["content"],
                    "modality": "video",
                    "evidence_type": "video_frame_ocr",
                    "locator": {
                        "kind": "video_frame",
                        "timestamp_ms": timestamp_ms,
                        "frame_path": str(relative_path),
                        "bbox": locator["bbox"],
                    },
                    "confidence": ocr_item.get("confidence"),
                }
            )

    if not frame_evidence:
        warnings.append(NO_FRAME_TEXT_WARNING)
    return evidence + frame_evidence, warnings


class VideoParseSkill:
    manifest = SkillManifest(
        id="video_parse",
        name="视频解析",
        version="1.0.0",
        description="解析 MP4 音轨和关键帧",
        enabled_by_default=True,
        required=False,
        input_types=["mp4"],
        output_type="evidence_list",
    )

    def run(self, context: SkillContext, payload: Any) -> SkillResult:
        started = perf_counter()
        file_info = payload["file"]
        try:
            if settings.mock_ai:
                evidence, warnings = mock_video_evidence(context, file_info)
            else:
                evidence, warnings = real_video_evidence(context, file_info)
        except Exception as exc:
            return SkillResult(
                success=False,
                errors=[f"视频解析失败: {type(exc).__name__}: {exc}"],
                data={"evidence": []},
                metrics={"duration_ms": int((perf_counter() - started) * 1000)},
            )

        return SkillResult(
            success=True,
            warnings=warnings,
            data={"evidence": evidence},
            metrics={"duration_ms": int((perf_counter() - started) * 1000), "evidence_count": len(evidence)},
        )
