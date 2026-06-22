from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from app.config import settings
from app.services.vision_client import VisionClient
from app.utils.health_details import redact_health_detail

from .base import SkillContext, SkillManifest, SkillResult
from .utils import coerce_items, derived_path, original_file_path, sidecar_fixture
from .video_parse import extract_video_frames

IMAGE_PROMPT = (
    "请用中文客观描述这张图片中的可见信息，重点关注场景、目标、车辆、人员、动作、地点线索和数量。"
    "只描述画面中能看到的内容，不要根据 OCR 或外部知识编造。"
)
VIDEO_FRAME_PROMPT = (
    "请用中文客观描述这个视频关键帧中的可见信息，重点关注场景、目标、车辆、人员、动作、地点线索和数量。"
    "只描述画面中能看到的内容，不要根据 OCR、音频或外部知识编造。"
)
NO_VIDEO_FRAMES_WARNING = "没有可用于视觉理解的视频关键帧"


class VisualUnderstandSkill:
    manifest = SkillManifest(
        id="visual_understand",
        name="视觉理解",
        version="1.0.0",
        description="对图片与视频关键帧生成画面描述",
        enabled_by_default=True,
        required=False,
        input_types=["jpg", "jpeg", "png", "mp4"],
        output_type="evidence_list",
    )

    def __init__(self, vision_client: VisionClient | None = None) -> None:
        self.vision_client = vision_client

    def run(self, context: SkillContext, payload: Any) -> SkillResult:
        started = perf_counter()
        file_info = payload["file"]
        try:
            if file_info.get("modality") == "video" or str(file_info.get("extension") or "").lower() == "mp4":
                evidence, warnings = self._run_video(context, file_info, payload)
            else:
                evidence, warnings = self._run_image(context, file_info)
        except Exception as exc:
            return SkillResult(
                success=True,
                warnings=[f"视觉理解失败: {type(exc).__name__}: {redact_health_detail(exc)}"],
                data={"evidence": []},
                metrics={"duration_ms": int((perf_counter() - started) * 1000)},
            )

        return SkillResult(
            success=True,
            warnings=warnings,
            data={"evidence": evidence},
            metrics={"duration_ms": int((perf_counter() - started) * 1000), "evidence_count": len(evidence)},
        )

    def _run_image(self, context: SkillContext, file_info: dict[str, Any]) -> tuple[list[dict], list[str]]:
        if settings.effective_mock_vision:
            caption = _fixture_image_caption(context, file_info) or _default_image_caption(file_info)
        else:
            caption = self._client().describe_image(original_file_path(context, file_info), IMAGE_PROMPT)
        return [_image_caption_evidence(caption)], []

    def _run_video(
        self,
        context: SkillContext,
        file_info: dict[str, Any],
        payload: Any,
    ) -> tuple[list[dict], list[str]]:
        if not settings.effective_mock_vision:
            return self._run_real_video(context, file_info, payload)

        frames = [frame for frame in list(payload.get("frames") or []) if isinstance(frame, dict)]
        if not frames:
            return [], [NO_VIDEO_FRAMES_WARNING]

        fixture = sidecar_fixture(context, file_info, "caption")
        evidence: list[dict] = []
        warnings: list[str] = []
        for index, frame in enumerate(frames):
            try:
                timestamp_ms = int(frame.get("timestamp_ms", 0))
                frame_path = str(frame.get("frame_path") or "")
                caption = _fixture_frame_caption(fixture, index=index, timestamp_ms=timestamp_ms)
                if caption is None:
                    caption = _default_frame_caption(file_info, timestamp_ms)
                evidence.append(_video_frame_caption_evidence(caption, timestamp_ms, frame_path))
            except Exception as exc:
                warnings.append(f"视频关键帧视觉理解失败: {type(exc).__name__}: {redact_health_detail(exc)}")
        return evidence, warnings

    def _run_real_video(
        self,
        context: SkillContext,
        file_info: dict[str, Any],
        payload: Any,
    ) -> tuple[list[dict], list[str]]:
        if settings.effective_mock_media:
            try:
                frames = extract_video_frames(context, file_info)
            except Exception as exc:
                return [], [f"视频视觉理解跳过: {type(exc).__name__}: {redact_health_detail(exc)}"]
        else:
            frames = [frame for frame in list(payload.get("frames") or []) if isinstance(frame, dict)]
        if not frames:
            return [], [NO_VIDEO_FRAMES_WARNING]

        evidence: list[dict] = []
        warnings: list[str] = []
        for frame in frames:
            try:
                timestamp_ms = int(frame.get("timestamp_ms", 0))
                frame_path = str(frame.get("frame_path") or "")
                absolute_frame = _safe_frame_path(context, frame_path)
                caption = self._client().describe_image(absolute_frame, VIDEO_FRAME_PROMPT)
                evidence.append(_video_frame_caption_evidence(caption, timestamp_ms, frame_path))
            except Exception as exc:
                warnings.append(f"视频关键帧视觉理解失败: {type(exc).__name__}: {redact_health_detail(exc)}")
        return evidence, warnings

    def _client(self) -> VisionClient:
        return self.vision_client or VisionClient()


def _image_caption_evidence(caption: str) -> dict:
    return {
        "content": caption,
        "modality": "image",
        "evidence_type": "image_caption",
        "locator": {"kind": "image"},
        "confidence": None,
    }


def _video_frame_caption_evidence(caption: str, timestamp_ms: int, frame_path: str) -> dict:
    return {
        "content": caption,
        "modality": "video",
        "evidence_type": "video_frame_caption",
        "locator": {
            "kind": "video_frame",
            "timestamp_ms": timestamp_ms,
            "frame_path": frame_path,
        },
        "confidence": None,
    }


def _fixture_image_caption(context: SkillContext, file_info: dict[str, Any]) -> str | None:
    fixture = sidecar_fixture(context, file_info, "caption")
    if isinstance(fixture, dict):
        caption = _caption_text(fixture)
        if caption:
            return caption
    for item in coerce_items(fixture, ("captions", "items")):
        caption = _caption_text(item)
        if caption:
            return caption
    return None


def _fixture_frame_caption(
    fixture: dict[str, Any] | list[Any] | None,
    *,
    index: int,
    timestamp_ms: int,
) -> str | None:
    raw_frames = coerce_items(fixture, ("frames", "captions", "items"))
    for raw in raw_frames:
        if not isinstance(raw, dict):
            continue
        if raw.get("timestamp_ms") is not None and int(raw.get("timestamp_ms", -1)) == timestamp_ms:
            caption = _caption_text(raw)
            if caption:
                return caption
    if index < len(raw_frames):
        return _caption_text(raw_frames[index])
    return None


def _caption_text(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, dict):
        text = str(value.get("caption") or value.get("text") or value.get("content") or "").strip()
    else:
        text = ""
    return text or None


def _default_image_caption(file_info: dict[str, Any]) -> str:
    return (
        f"MOCK 画面描述：{file_info['original_name']} 显示一处训练场景，"
        "可见用于复核的目标、车辆、人员或地点线索。"
    )


def _default_frame_caption(file_info: dict[str, Any], timestamp_ms: int) -> str:
    return (
        f"MOCK 视频画面描述：{file_info['original_name']} 在 {timestamp_ms / 1000:.1f}s 的关键帧"
        "显示一处训练场景，可见用于复核的目标、车辆、人员或地点线索。"
    )


def _safe_frame_path(context: SkillContext, frame_path: str) -> Path:
    absolute = derived_path(context, frame_path)
    frames_root = derived_path(context, "derived/frames")
    if not absolute.is_relative_to(frames_root):
        raise ValueError("frame path escaped derived/frames")
    return absolute
