from pathlib import Path
from time import perf_counter
from typing import Any

from app.config import PROJECT_ROOT, settings

from .base import SkillContext, SkillManifest, SkillResult
from .utils import coerce_items, original_file_path, sidecar_fixture

_ASR_MODEL = None
NO_SPEECH_WARNING = "ASR 未识别到语音文本"


def _default_segments() -> list[dict[str, Any]]:
    return [
        {"text": "MOCK 音频第一段", "start_ms": 0, "end_ms": 2500, "confidence": None},
        {"text": "MOCK 音频第二段", "start_ms": 2500, "end_ms": 5000, "confidence": None},
    ]


def resolve_asr_model_path() -> Path:
    if not settings.asr_model_dir:
        raise RuntimeError("ASR_MODEL_DIR 未配置，真实 ASR 需要本地模型目录")

    model_root = Path(settings.asr_model_dir).expanduser()
    if not model_root.is_absolute():
        model_root = PROJECT_ROOT / model_root
    model_root = model_root.resolve()
    if not model_root.is_dir():
        raise RuntimeError(f"ASR_MODEL_DIR 不存在: {model_root}")

    sized_model = model_root / settings.asr_model_size
    return sized_model if sized_model.is_dir() else model_root


def _segment_evidence(
    segment: dict[str, Any],
    *,
    modality: str,
    locator_kind: str,
) -> dict | None:
    text = str(segment.get("text") or segment.get("content") or "").strip()
    if not text:
        return None
    start_ms = int(segment.get("start_ms", 0))
    end_ms = int(segment.get("end_ms", start_ms))
    return {
        "content": text,
        "modality": modality,
        "evidence_type": "asr",
        "locator": {"kind": locator_kind, "start_ms": start_ms, "end_ms": end_ms},
        "confidence": segment.get("confidence"),
    }


def mock_transcript_evidence(
    context: SkillContext,
    file_info: dict[str, Any],
    *,
    modality: str = "audio",
    locator_kind: str = "audio",
) -> tuple[list[dict], list[str]]:
    fixture = sidecar_fixture(context, file_info, "asr")
    raw_segments = coerce_items(fixture, ("segments", "items", "transcript"))
    if fixture is None:
        raw_segments = _default_segments()

    evidence = []
    for raw in raw_segments:
        if isinstance(raw, dict):
            item = _segment_evidence(raw, modality=modality, locator_kind=locator_kind)
            if item is not None:
                evidence.append(item)

    warnings = [NO_SPEECH_WARNING] if not evidence else []
    return evidence, warnings


def real_transcript_evidence(
    path: Path,
    *,
    modality: str = "audio",
    locator_kind: str = "audio",
) -> tuple[list[dict], list[str]]:
    global _ASR_MODEL
    if _ASR_MODEL is None:
        from faster_whisper import WhisperModel

        _ASR_MODEL = WhisperModel(
            str(resolve_asr_model_path()),
            device="cpu",
            compute_type="int8",
            local_files_only=True,
        )

    segments, _ = _ASR_MODEL.transcribe(str(path), vad_filter=True)
    evidence: list[dict] = []
    for segment in segments:
        item = _segment_evidence(
            {
                "text": segment.text,
                "start_ms": int(segment.start * 1000),
                "end_ms": int(segment.end * 1000),
                "confidence": None,
            },
            modality=modality,
            locator_kind=locator_kind,
        )
        if item is not None:
            evidence.append(item)

    warnings = [NO_SPEECH_WARNING] if not evidence else []
    return evidence, warnings


class AudioTranscribeSkill:
    manifest = SkillManifest(
        id="audio_transcribe",
        name="音频转写",
        version="1.0.0",
        description="转写 WAV、MP3 和 M4A 音频",
        enabled_by_default=True,
        required=False,
        input_types=["wav", "mp3", "m4a"],
        output_type="evidence_list",
    )

    def run(self, context: SkillContext, payload: Any) -> SkillResult:
        started = perf_counter()
        file_info = payload["file"]
        try:
            if settings.effective_mock_media:
                evidence, warnings = mock_transcript_evidence(context, file_info)
            else:
                evidence, warnings = real_transcript_evidence(original_file_path(context, file_info))
        except Exception as exc:
            return SkillResult(
                success=False,
                errors=[f"ASR 转写失败: {type(exc).__name__}: {exc}"],
                data={"evidence": []},
                metrics={"duration_ms": int((perf_counter() - started) * 1000)},
            )

        return SkillResult(
            success=True,
            warnings=warnings,
            data={"evidence": evidence},
            metrics={"duration_ms": int((perf_counter() - started) * 1000), "evidence_count": len(evidence)},
        )
